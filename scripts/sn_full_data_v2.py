#!/usr/bin/env python3
"""
SN 设备全生命周期原始数据报告脚本 (带生产间隔分析)
输出位置: ~/Documents/MySQL/
"""
import pymysql
import os
import json
from datetime import datetime, timedelta

CONFIG_PATH = os.path.expanduser('~/Projects/zhiku-agent/config/db_config.env')
OUTPUT_DIR = os.path.expanduser('~/Documents/MySQL')

def load_config():
    config = {}
    with open(CONFIG_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                config[k.strip()] = v.strip()
    return config

def query(cursor, sql, args):
    cursor.execute(sql, args)
    return cursor.fetchall()

def run():
    config = load_config()
    sn = '0105222512010046'
    conn = pymysql.connect(
        host=config['DB_HOST'], port=int(config['DB_PORT']),
        user=config['DB_USER'], password=config['DB_PASSWORD'],
        charset=config['DB_CHARSET'], cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()

    lines = []
    lines.append(f"# 设备 SN `{sn}` 全生命周期数据报告\n")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    lines.append(f"**数据来源**: 公司后台 MySQL (btyc / manage_backend)\n")
    lines.append("---\n")

    # 1. 设备基础档案
    lines.append("## 1. 设备基础档案 (sop_robot)\n")
    robot = query(cursor, "SELECT * FROM btyc.sop_robot WHERE machinecode = %s", (sn,))
    if robot:
        r = robot[0]
        lines.append("| 字段 | 值 |")
        lines.append("|---|---|")
        for k, v in r.items():
            if v is not None and v != '':
                lines.append(f"| **{k}** | `{v}` |")
    else:
        lines.append("未找到设备主档。")
    lines.append("")

    # 2. 生产间隔分析 (核心)
    lines.append("## 2. 生产周期与间隔分析 (sop_machinelog)\n")

    all_logs = query(cursor, "SELECT * FROM btyc.sop_machinelog WHERE sn = %s ORDER BY create_time ASC", (sn,))
    count = len(all_logs)
    lines.append(f"**总生产记录数**: {count} 条\n")

    if all_logs:
        # 间隔分析
        lines.append("### 2.1 生产间隔明细\n")
        lines.append("| 序号 | 执行时间 (开始) | 执行时间 (结束) | 菜谱名称 | 耗时(s) | **距离上次生产间隔** |")
        lines.append("|---|---|---|---|---|---|")

        last_time = None
        for i, row in enumerate(all_logs):
            current_time = row['create_time']
            end_time = row.get('end_time') or row.get('data_time')

            interval_str = "**首次运行**"
            if last_time:
                delta = current_time - last_time
                if delta.total_seconds() > 0:
                    days = delta.days
                    hours, remainder = divmod(delta.seconds, 3600)
                    minutes, _ = divmod(remainder, 60)
                    if days > 0:
                        interval_str = f"⚠️ **{days} 天 {hours} 小时 {minutes} 分**"
                    else:
                        interval_str = f"{hours}h {minutes}m"

            end_str = str(end_time) if end_time else "无记录"

            lines.append(f"| {i+1} | {current_time} | {end_str} | {row['recipe_name']} | {row['time']} | {interval_str} |")
            last_time = current_time
        lines.append("")

        # 月度汇总
        lines.append("### 2.2 月度活跃度\n")
        lines.append("| 月份 | 执行次数 | 活跃天数 | 备注 |")
        lines.append("|---|---|---|---|")

        monthly = {}
        for row in all_logs:
            m = row['create_time'].strftime('%Y-%m')
            if m not in monthly:
                monthly[m] = {'cnt': 0, 'days': set()}
            monthly[m]['cnt'] += 1
            monthly[m]['days'].add(row['create_time'].day)

        for m in sorted(monthly.keys()):
            d = monthly[m]
            lines.append(f"| {m} | {d['cnt']} | {len(d['days'])} |  |")
        lines.append("")

    # 3. 维护与故障日志
    lines.append("## 3. 维护与故障日志\n")

    pot_logs = query(cursor, "SELECT * FROM btyc.robot_conservation_pot_log WHERE machine_code = %s ORDER BY create_time DESC", (sn,))
    lines.append(f"### 3.1 养锅/维护日志 ({len(pot_logs)} 条)\n")
    if pot_logs:
        lines.append("| 时间 | 状态 | 备注 |")
        lines.append("|---|---|---|")
        for p in pot_logs:
            lines.append(f"| {p['create_time']} | {p.get('status')} | {p.get('remark', '')} |")
    lines.append("")

    fault_logs = query(cursor, "SELECT * FROM btyc.bytc_robot_malfunctions_log WHERE sn = %s ORDER BY create_time DESC", (sn,))
    lines.append(f"### 3.2 故障日志 ({len(fault_logs)} 条)\n")
    if fault_logs:
        lines.append("| 时间 | 模块 | 二级故障详情 | 状态 |")
        lines.append("|---|---|---|---|")
        for f in fault_logs:
            details = f.get('second_level_error_details', '')[:60]
            lines.append(f"| {f['create_time']} | {f.get('module')} | {details} | {f.get('deal_state')} |")
    lines.append("")

    # 4. 菜谱成分溯源
    lines.append("## 4. 菜谱成分溯源分析\n")
    recipe_ids = list(set([r['recipe_id'] for r in all_logs]))
    if recipe_ids:
        placeholders = ','.join(['%s'] * len(recipe_ids))
        recipes = query(cursor, f"SELECT id, name, steps_describe, ingredients_total_dosage FROM manage_backend.main_recipe WHERE id IN ({placeholders})", tuple(recipe_ids))

        has_lard = False
        lines.append("| 菜谱 ID | 名称 | 含猪油? | 关键配料/步骤摘要 |")
        lines.append("|---|---|---|---|")
        for r in recipes:
            is_lard = '猪油' in str(r.get('name', '')) or '猪油' in str(r.get('steps_describe', '')) or '猪油' in str(r.get('ingredients_total_dosage', ''))
            if is_lard: has_lard = True
            summary = ""
            if is_lard:
                summary = "⚠️ 含猪油"
            else:
                ing = str(r.get('ingredients_total_dosage', ''))[:60]
                summary = ing if ing else "无配料记录"
            status = "是" if is_lard else "否"
            lines.append(f"| {r['id']} | {r['name']} | {status} | {summary} |")

        if not has_lard:
            lines.append("\n**结论**: 历史使用菜谱均**未包含**猪油成分。")
    lines.append("")

    # 5. 设备配置
    lines.append("## 5. 设备配置快照\n")
    cfgs = query(cursor, "SELECT config FROM btyc.robot_config_info WHERE sn = %s ORDER BY create_time DESC LIMIT 1", (sn,))
    if cfgs and cfgs[0].get('config'):
        try:
            lines.append("```json")
            lines.append(json.dumps(json.loads(cfgs[0]['config']), indent=2, ensure_ascii=False))
            lines.append("```\n")
        except: pass
    lines.append("")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, f"report_{sn}.md")
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"✅ 报告已生成: {filepath}")
    conn.close()

if __name__ == '__main__':
    run()
