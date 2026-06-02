#!/usr/bin/env python3
"""
智库 Agent - 后台数据库查询工具
用法: python3 query.py "SELECT * FROM btyc.ums_admin LIMIT 5"
输出: 表格格式 + CSV 保存到 output/ 目录
"""

import pymysql
import os
import sys
import csv
from datetime import datetime

def load_config():
    config = {}
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'db_config.env')
    with open(config_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                config[key.strip()] = value.strip()
    return config

def execute_query(sql, output_format='table', save_csv=True):
    config = load_config()

    print(f"🔍 执行查询: {sql[:120]}{'...' if len(sql) > 120 else ''}")
    print(f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    conn = pymysql.connect(
        host=config['DB_HOST'],
        port=int(config['DB_PORT']),
        user=config['DB_USER'],
        password=config['DB_PASSWORD'],
        charset=config.get('DB_CHARSET', 'utf8mb4'),
        cursorclass=pymysql.cursors.DictCursor
    )

    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()

        if not rows:
            print("✅ 查询成功，返回 0 行")
            return []

        columns = list(rows[0].keys())
        print(f"✅ 查询成功，返回 {len(rows)} 行 × {len(columns)} 列")
        print()

        # Table output
        if output_format == 'table':
            # Calculate column widths
            col_widths = {col: len(str(col)) for col in columns}
            for row in rows[:50]:  # Display first 50 rows
                for col in columns:
                    val_len = len(str(row[col]))
                    col_widths[col] = max(col_widths[col], min(val_len, 80))

            # Header
            header = ' | '.join(str(col).ljust(col_widths[col]) for col in columns)
            separator = '-+-'.join('-' * col_widths[col] for col in columns)
            print(header)
            print(separator)

            # Rows (limit display to 50)
            display_rows = rows[:50]
            for i, row in enumerate(display_rows):
                vals = []
                for col in columns:
                    val = str(row[col])
                    if len(val) > 80:
                        val = val[:77] + '...'
                    vals.append(val.ljust(col_widths[col]))
                print(' | '.join(vals))

            if len(rows) > 50:
                print(f"\n... 还有 {len(rows) - 50} 行未显示")

        # Save to CSV
        if save_csv:
            output_dir = os.path.join(os.path.dirname(__file__), '..', 'output')
            os.makedirs(output_dir, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"query_{timestamp}.csv"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)

            print(f"\n💾 已保存到: {filepath}")

        return rows

    finally:
        conn.close()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python3 query.py 'SELECT ...'")
        print("\n示例:")
        print("  python3 query.py 'SELECT COUNT(*) FROM btyc.ums_admin'")
        print("  python3 query.py 'SELECT * FROM btyc.ums_admin LIMIT 10'")
        sys.exit(1)

    sql = ' '.join(sys.argv[1:])
    execute_query(sql)
