#!/usr/bin/env python3
"""
SN 设备全生命周期原始数据报告脚本
输出结构：概览 -> 原始数据明细 -> 专项分析
"""
import pymysql
import os
import json
from datetime import datetime

CONFIG_PATH = os.path.expanduser('~/Projects/zhiku-agent/config/db_config.env')
OUTPUT_PATH = os.path.expanduser('~/Projects/zhiku-agent/output/sn_full_data_report.md')

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
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**数据来源**: 公司后台 MySQL (只读)\n")
    lines.append("---\n")

    # 1. 设备基础档案
    lines.append("## 1. 设备基础档案 (sop_robot)\n")
    robot = query(cursor, "SELECT * FROM btyc.sop_robot WHERE machinecode = %s", (sn,))
    if robot:
        r = robot[0]
        for k, v in r.items():
            if v is not None and v != '':
                lines.append(f"- **{k}**: `{v}`")
    else:
        lines.append("未找到设备主档。")
    lines.append("")

    # 2. 烹饪日志原始数据 (sop_machinelog)
    lines.append("## 2. 烹饪日志 (sop_machinelog)\n")
    count = query(cursor, "SELECT COUNT(*) as c FROM btyc.sop_machinelog WHERE sn = %s", (sn,))[0]['c']
    lines.append(f"**总记录数**: {count} 条\n")

    # 2.1 按月汇总
    lines.append("### 2.1 月度执行汇总\n")
    lines.append("| 月份 | 次数 | 菜谱数 | 首次执行 | 末次执行 |")
    lines.append("|---|---|---|---|---|")
    summary = query(cursor, """
        SELECT DATE_FORMAT(create_time, '%%Y-%%m') as m, COUNT(*) as cnt,
               COUNT(DISTINCT recipe_id) as rc, MIN(create_time) as min_t, MAX(create_time) as max_t
        FROM btyc.sop_machinelog WHERE sn = %s GROUP BY m ORDER BY m
    """, (sn,))
    for row in summary:
        lines.append(f"| {row['m']} | {row['cnt']} | {row['rc']} | {row['min_t']} | {row['max_t']} |")
    lines.append("")

    # 2.2 菜谱使用明细 (全量)
    lines.append("### 2.2 菜谱使用统计\n")
    lines.append("| 菜谱 ID | 菜谱名称 | 执行次数 | 占比 | 累计时长 (分) |")
    lines.append("|---|---|---|---|---|")
    recipe_stats = query(cursor, """
        SELECT recipe_id, recipe_name, COUNT(*) as cnt, SUM(CAST(time AS SIGNED)) as total_s
        FROM btyc.sop_machinelog WHERE sn = %s
        GROUP BY recipe_id, recipe_name ORDER BY cnt DESC
    """, (sn,))
    for row in recipe_stats:
        ratio = f"{(row['cnt']/count)*100:.1f}%"
        minutes = int(row['total_s'] or 0) / 60
        lines.append(f"| {row['recipe_id']} | {row['recipe_name']} | {row['cnt']} | {ratio} | {minutes:.0f} |")
    lines.append("")

    # 2.3 最近 10 条执行明细
    lines.append("### 2.3 最近 10 条执行明细\n")
    lines.append("| ID | 时间 | 菜谱 | 耗时(s) | 账号 |")
    lines.append("|---|---|---|---|---|")
    recent = query(cursor, "SELECT * FROM btyc.sop_machinelog WHERE sn = %s ORDER BY create_time DESC LIMIT 10", (sn,))
    for row in recent:
        lines.append(f"| {row['id']} | {row['create_time']} | {row['recipe_name']} | {row['time']} | {row['username']} |")
    lines.append("")

    # 3. 维护与故障日志
    lines.append("## 3. 维护与故障日志\n")

    # 3.1 维护日志
    pot_logs = query(cursor, "SELECT * FROM btyc.robot_conservation_pot_log WHERE machine_code = %s ORDER BY create_time DESC", (sn,))
    lines.append(f"### 3.1 养锅/维护日志 ({len(pot_logs)} 条)\n")
    if pot_logs:
        lines.append("| 时间 | 状态 | 备注/描述 |")
        lines.append("|---|---|---|")
        for p in pot_logs:
            lines.append(f"| {p['create_time']} | {p.get('status')} | {p.get('remark', '')} |")
    lines.append("")

    # 3.2 故障日志
    fault_logs = query(cursor, "SELECT * FROM btyc.bytc_robot_malfunctions_log WHERE sn = %s ORDER BY create_time DESC", (sn,))
    lines.append(f"### 3.2 故障日志 ({len(fault_logs)} 条)\n")
    if fault_logs:
        lines.append("| 时间 | 模块 | 二级故障详情 | 状态 |")
        lines.append("|---|---|---|---|")
        for f in fault_logs:
            details = f.get('second_level_error_details', '')[:50]
            lines.append(f"| {f['create_time']} | {f.get('module')} | {details} | {f.get('deal_state')} |")
    lines.append("")

    # 4. 菜谱成分溯源 (关联猪油)
    lines.append("## 4. 菜谱成分溯源分析\n")
    recipe_ids = [r['recipe_id'] for r in recipe_stats]
    if recipe_ids:
        placeholders = ','.join(['%s'] * len(recipe_ids))
        recipes = query(cursor, f"SELECT id, name, steps_describe, ingredients_total_dosage FROM manage_backend.main_recipe WHERE id IN ({placeholders})", tuple(recipe_ids))

        has_lard = False
        lines.append("| 菜谱 ID | 名称 | 含猪油? | 关键配料/步骤摘要 |")
        lines.append("|---|---|---|---|")
        for r in recipes:
            is_lard = '猪油' in str(r.get('name', '')) or '猪油' in str(r.get('steps_describe', '')) or '猪油' in str(r.get('ingredients_total_dosage', ''))
            if is_lard: has_lard = True

            # 摘要
            summary_text = ''
            if '猪油' in str(r.get('name', '')): summary_text += f"名称含猪油; "
            if '猪油' in str(r.get('steps_describe', '')): summary_text += f"步骤含猪油; "
            if '猪油' in str(r.get('ingredients_total_dosage', '')): summary_text += f"配料含猪油; "
            if not is_lard:
                # 提取一些主要配料
                ing = str(r.get('ingredients_total_dosage', ''))
                summary_text = f"主要配料: {ing[:60]}..." if len(ing) > 60 else ing

            status = "⚠️ 是" if is_lard else "✅ 否"
            lines.append(f"| {r['id']} | {r['name']} | {status} | {summary_text} |")

        if not has_lard:
            lines.append("\n**结论**: 该设备历史使用的所有菜谱中，均**未包含**猪油成分。")
    lines.append("")

    # 5. 设备配置快照
    lines.append("## 5. 设备配置快照\n")
    cfgs = query(cursor, "SELECT * FROM btyc.robot_config_info WHERE sn = %s ORDER BY create_time DESC LIMIT 1", (sn,))
    if cfgs and cfgs[0].get('config'):
        try:
            config_data = json.loads(cfgs[0]['config'])
            lines.append("### 5.1 当前 JSON 配置\n")
            lines.append("```json")
            lines.append(json.dumps(config_data, indent=2, ensure_ascii=False))
            lines.append("```\n")
        except:
            lines.append("配置解析失败。")
    lines.append("")

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"✅ 报告已生成: {OUTPUT_PATH}")
    conn.close()

if __name__ == '__main__':
    run()
