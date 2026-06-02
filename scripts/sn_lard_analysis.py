#!/usr/bin/env python3
"""
SN 设备全生命周期数据调查脚本
覆盖从装机第一天到现在的所有数据
"""
import pymysql
import os
import json
from datetime import datetime

CONFIG_PATH = os.path.expanduser('~/Projects/zhiku-agent/config/db_config.env')

def load_config():
    config = {}
    with open(CONFIG_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                config[k.strip()] = v.strip()
    return config

def run():
    config = load_config()
    sn = '0105222512010046'

    conn = pymysql.connect(
        host=config['DB_HOST'], port=int(config['DB_PORT']),
        user=config['DB_USER'], password=config['DB_PASSWORD'],
        charset=config['DB_CHARSET'], cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()

    report = [f"# 设备 SN {sn} 全生命周期数据分析报告\n"]
    report.append(f"**生成时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"**设备 SN:** {sn}")
    report.append(f"**数据范围:** 装机第一天 ~ 至今\n")
    report.append("---\n")

    # 1. 烹饪日志总览 (sop_machinelog)
    print("=== 1. 全生命周期烹饪日志统计 ===")
    cursor.execute("""
        SELECT MIN(create_time) as first_date, MAX(create_time) as last_date,
               COUNT(*) as total_logs, SUM(CAST(time AS UNSIGNED)) as total_time
        FROM btyc.sop_machinelog WHERE sn = %s
    """, (sn,))
    summary = cursor.fetchone()

    first_date = summary['first_date']
    last_date = summary['last_date']
    total_logs = summary['total_logs']
    total_hours = (int(summary['total_time']) / 3600) if summary['total_time'] else 0

    report.append(f"## 📅 运行概况")
    report.append(f"- **装机时间:** {first_date}")
    report.append(f"- **最新运行:** {last_date}")
    report.append(f"- **总烹饪次数:** {total_logs} 次")
    report.append(f"- **总烹饪时长:** {total_hours:.1f} 小时")

    # 2. 历史菜谱分析与猪油排查
    print("\n=== 2. 菜谱分析与猪油排查 ===")
    cursor.execute("SELECT DISTINCT recipe_id FROM btyc.sop_machinelog WHERE sn = %s", (sn,))
    all_recipe_ids = [r['recipe_id'] for r in cursor.fetchall()]
    report.append(f"\n## 🔍 菜谱使用与猪油成分溯源")
    report.append(f"- **历史使用菜谱总数:** {len(all_recipe_ids)} 个")

    if all_recipe_ids:
        placeholders = ','.join(['%s'] * len(all_recipe_ids))
        cursor.execute(f"""
            SELECT id, name, steps_describe, ingredients_total_dosage
            FROM manage_backend.main_recipe WHERE id IN ({placeholders})
        """, tuple(all_recipe_ids))
        recipes = cursor.fetchall()

        lard_recipes = []
        for r in recipes:
            is_lard = False
            if '猪油' in str(r.get('name', '')): is_lard = True
            if '猪油' in str(r.get('steps_describe', '')): is_lard = True
            if '猪油' in str(r.get('ingredients_total_dosage', '')): is_lard = True
            if is_lard:
                lard_recipes.append(r)

        report.append(f"- **含“猪油”成分的菜谱:** {len(lard_recipes)} 个")
        if lard_recipes:
            report.append("  > **⚠️ 发现以下菜谱涉及猪油：**")
            for lr in lard_recipes:
                report.append(f"  - `{lr['name']}` (ID: {lr['id']})")
        else:
            report.append("  > ✅ 该设备历史使用的所有菜谱中，**均未发现猪油成分或投料指令。**")

        # 统计高频菜谱
        cursor.execute(f"""
            SELECT recipe_id, recipe_name, COUNT(*) as cnt
            FROM btyc.sop_machinelog WHERE sn = %s
            GROUP BY recipe_id, recipe_name ORDER BY cnt DESC LIMIT 5
        """, (sn,))
        top_recipes = cursor.fetchall()
        report.append(f"\n### 🔥 历史高频菜谱 TOP 5")
        for r in top_recipes:
            report.append(f"- {r['recipe_name']}: 执行 {r['cnt']} 次")

    # 3. 维护与故障日志
    print("\n=== 3. 维护与故障日志 ===")

    # 维护日志总数
    cursor.execute("SELECT COUNT(*) as cnt FROM btyc.robot_conservation_pot_log WHERE machine_code = %s", (sn,))
    pot_cnt = cursor.fetchone()['cnt']
    report.append(f"\n## 🛠 设备维护与故障")
    report.append(f"- **养锅/维护记录:** {pot_cnt} 次")

    # 故障日志总数
    cursor.execute("SELECT COUNT(*) as cnt FROM btyc.bytc_robot_malfunctions_log WHERE sn = %s", (sn,))
    fault_cnt = cursor.fetchone()['cnt']
    report.append(f"- **设备故障日志总数:** {fault_cnt} 条")

    # 查找是否有油相关的故障
    cursor.execute("""
        SELECT second_level_error_details, create_time
        FROM btyc.bytc_robot_malfunctions_log
        WHERE sn = %s AND second_level_error_details LIKE '%%油%%'
        ORDER BY create_time DESC LIMIT 3
    """, (sn,))
    oil_faults = cursor.fetchall()

    if oil_faults:
        report.append("- **⚠️ 历史含“油”故障记录:**")
        for f in oil_faults:
            report.append(f"  - {f['create_time']}: {f['second_level_error_details']}")
    else:
        report.append("- **历史含“油”故障记录:** 0 条")

    # 4. 写入报告
    md_path = os.path.expanduser('~/Projects/zhiku-agent/output/sn_lard_analysis.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report))
        f.write("\n\n---\n*报告由 智库 Agent 自动生成*\n")

    print(f"\n💾 报告已更新: {md_path}")
    conn.close()

if __name__ == '__main__':
    run()
