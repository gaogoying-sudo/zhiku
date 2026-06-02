#!/usr/bin/env python3
"""
SN 设备深度调查脚本 - 针对 SN: 105222512010046
查询设备基本信息、近 7 天烹饪日志、菜谱详情、猪油相关成分
"""
import pymysql
import os
import json
from datetime import datetime, timedelta

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
    sn_input = '105222512010046'
    sn_patterns = [f'%{sn_input}', f'%0{sn_input}']

    conn = pymysql.connect(
        host=config['DB_HOST'], port=int(config['DB_PORT']),
        user=config['DB_USER'], password=config['DB_PASSWORD'],
        charset=config['DB_CHARSET'], cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()

    report = []

    # 1. 设备主档案
    print("=== 1. 查询设备主档案 (sop_robot) ===")
    cursor.execute("SELECT * FROM btyc.sop_robot WHERE machinecode LIKE %s LIMIT 1", (sn_patterns[0],))
    robot = cursor.fetchone()
    if not robot:
        cursor.execute("SELECT * FROM btyc.sop_robot WHERE machinecode LIKE %s LIMIT 1", (sn_patterns[1],))
        robot = cursor.fetchone()

    if robot:
        real_sn = robot['machinecode']
        print(f"✅ 找到设备: {real_sn} | company_id: {robot.get('company_id')} | owner: {robot.get('owner')}")
        report.append(f"**设备 SN:** {real_sn}")
        report.append(f"**归属门店 ID:** {robot.get('company_id')} / {robot.get('owner')}")
        report.append(f"**设备状态:** {robot.get('status')} / {robot.get('is_active')}")
    else:
        print("❌ 未找到设备主档案")
        return

    # 2. 近 7 天烹饪日志
    print("\n=== 2. 查询近 7 天烹饪日志 (sop_machinelog) ===")
    days_ago = datetime.now() - timedelta(days=7)

    # 先查字段
    cursor.execute("SHOW COLUMNS FROM btyc.sop_machinelog")
    log_cols = {c['Field'] for c in cursor.fetchall()}
    time_col = 'cook_time' if 'cook_time' in log_cols else ('duration' if 'duration' in log_cols else 'create_time')
    status_col = 'status' if 'status' in log_cols else ('execution_status' if 'execution_status' in log_cols else 'id')

    cursor.execute(f"""
        SELECT id, sn, recipe_id, recipe_name, username, create_time, {time_col}, {status_col}
        FROM btyc.sop_machinelog
        WHERE sn = %s AND create_time >= %s
        ORDER BY create_time DESC
    """, (real_sn, days_ago))
    logs = cursor.fetchall()
    print(f"✅ 近 7 天执行记录: {len(logs)} 条")
    report.append(f"\n**近 7 天烹饪执行:** {len(logs)} 次")

    recipe_ids = list(set([l['recipe_id'] for l in logs if l['recipe_id']]))
    print(f"   涉及菜谱 ID: {recipe_ids[:10]}")

    # 统计
    stats = {}
    for l in logs:
        rid = l['recipe_id']
        rname = l['recipe_name'] or '未知'
        key = f"{rid} - {rname}"
        stats[key] = stats.get(key, 0) + 1

    top_recipes = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:5]
    report.append("\n**高频菜谱 (近 7 天):**")
    for name, count in top_recipes:
        report.append(f"- {name}: {count} 次")

    # 最近 5 条明细
    report.append("\n**最近 5 次执行明细:**")
    for l in logs[:5]:
        val = l.get(time_col, 'N/A')
        report.append(f"- {l['create_time']} | {l['recipe_name']} | {time_col}: {val} | {status_col}: {l.get(status_col)}")

    # 3. 菜谱成分分析 (重点查猪油)
    print("\n=== 3. 查询菜谱成分 (base_ingredients / sop_recipe) ===")
    cursor.execute("SELECT * FROM btyc.base_ingredients WHERE ingredients_name LIKE '%猪油%' OR ingredients_name LIKE '%lard%'")
    lard_ingredients = cursor.fetchall()
    print(f"   数据库中含'猪油'的基础食材: {len(lard_ingredients)} 种")
    for ing in lard_ingredients:
        print(f"   - ID:{ing['ingredinent_id']} 名称:{ing['ingredients_name']} 类型:{ing.get('ingredinent_type')}")

    lard_ids = [ing['ingredinent_id'] for ing in lard_ingredients]
    lard_names = [ing['ingredients_name'] for ing in lard_ingredients]

    # 检查执行的菜谱是否包含猪油相关信息
    if recipe_ids:
        placeholders = ','.join(['%s'] * len(recipe_ids))
        # 检查 sop_recipe 的 name, steps_describe, ingredients_total_dosage, oil_content 等字段
        cursor.execute(f"SELECT id, name, steps_describe, ingredients_total_dosage, oil_content FROM btyc.sop_recipe WHERE id IN ({placeholders})", tuple(recipe_ids))
        recipes = cursor.fetchall()

        lard_used = []
        for r in recipes:
            is_lard = False
            if '猪油' in (r['name'] or ''):
                is_lard = True
            for field in ['steps_describe', 'ingredients_total_dosage', 'oil_content']:
                val = r.get(field, '')
                if val and '猪油' in str(val):
                    is_lard = True
            if is_lard:
                lard_used.append(r)

        report.append(f"\n**猪油相关菜谱分析:**")
        if lard_used:
            for r in lard_used:
                report.append(f"⚠️ 菜谱 `{r['name']}` (ID:{r['id']}) **包含猪油成分或相关描述**")
        else:
            report.append("✅ 近 7 天执行的菜谱中，未发现明确标记为'猪油'的食材或步骤。")

    # 4. 猪油桶/直油桶相关日志
    print("\n=== 4. 查询猪油桶/直油桶相关维护日志 ===")
    # 检查 conservation_pot_log
    cursor.execute("SHOW COLUMNS FROM btyc.robot_conservation_pot_log")
    pot_cols = {c['Field'] for c in cursor.fetchall()}
    mc_col = 'machine_code' if 'machine_code' in pot_cols else ('sn' if 'sn' in pot_cols else 'machinecode')

    cursor.execute(f"""
        SELECT * FROM btyc.robot_conservation_pot_log
        WHERE {mc_col} = %s ORDER BY create_time DESC LIMIT 5
    """, (real_sn,))
    pot_logs = cursor.fetchall()
    report.append(f"\n**设备维护日志 (robot_conservation_pot_log):** {len(pot_logs)} 条")
    if pot_logs:
        for p in pot_logs[:3]:
            report.append(f"- {p.get('create_time')}: 类型={p.get('type')} 状态={p.get('status')} 备注={p.get('remark', p.get('description', ''))}")

    # 检查 fault logs 是否包含 油/猪油/lard/桶
    cursor.execute("SHOW COLUMNS FROM btyc.bytc_robot_malfunctions_log")
    fault_cols = {c['Field'] for c in cursor.fetchall()}
    fault_sn = 'sn' if 'sn' in fault_cols else ('machine_code' if 'machine_code' in fault_cols else 'machinecode')

    cursor.execute(f"""
        SELECT * FROM btyc.bytc_robot_malfunctions_log
        WHERE {fault_sn} = %s AND (second_level_error_details LIKE '%%油%%' OR second_level_error_details LIKE '%%猪油%%' OR second_level_error_details LIKE '%%桶%%')
        ORDER BY create_time DESC LIMIT 5
    """, (real_sn,))
    fault_logs = cursor.fetchall()
    report.append(f"\n**设备故障日志 (含'油/桶'关键词):** {len(fault_logs)} 条")
    if fault_logs:
        for f in fault_logs:
            report.append(f"- {f.get('create_time')}: {f.get('second_level_error_details', f.get('malfunction_id', ''))}")
    else:
        report.append("未发现明确与'油'或'桶'相关的故障记录。")

    # 5. 输出报告
    md_path = os.path.expanduser('~/Projects/zhiku-agent/output/sn_lard_analysis.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write("# 设备 SN 使用数据与猪油成分分析报告\n\n")
        f.write(f"**生成时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**设备 SN:** {real_sn}\n\n")
        f.write("---\n\n")
        for line in report:
            f.write(line + "\n")
        f.write("\n---\n*报告由 智库 Agent 自动生成*\n")

    print(f"\n💾 报告已生成: {md_path}")
    conn.close()

if __name__ == '__main__':
    run()
