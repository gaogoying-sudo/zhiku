#!/usr/bin/env python3
"""
智库 Agent - Schema 探索工具
用法: python3 explore_schema.py [数据库名]
默认: 探索所有 6 个库的表结构
"""

import pymysql
import os
import json
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

def get_table_info(db_name, table_name, cursor):
    """Get column info for a table"""
    cursor.execute(f"""
        SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_KEY, COLUMN_COMMENT
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """, (db_name, table_name))
    return cursor.fetchall()

def get_row_count(db_name, table_name, cursor):
    """Get approximate row count"""
    try:
        cursor.execute(f"""
            SELECT TABLE_ROWS FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        """, (db_name, table_name))
        result = cursor.fetchone()
        return result['TABLE_ROWS'] if result else 0
    except:
        return -1

def explore_database(db_name, max_tables=50):
    config = load_config()
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

        # Get tables
        cursor.execute(f"""
            SELECT TABLE_NAME, TABLE_ROWS, TABLE_COMMENT
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_ROWS DESC
        """, (db_name,))
        tables = cursor.fetchall()

        print(f"\n{'='*80}")
        print(f"📦 数据库: {db_name} ({len(tables)} 张表)")
        print(f"{'='*80}")

        schema = {
            'database': db_name,
            'table_count': len(tables),
            'export_time': datetime.now().isoformat(),
            'tables': []
        }

        for i, table in enumerate(tables[:max_tables]):
            tname = table['TABLE_NAME']
            rows = table['TABLE_ROWS'] or 0
            comment = table.get('TABLE_COMMENT', '') or ''

            cols = get_table_info(db_name, tname, cursor)

            print(f"\n  [{i+1}] {tname} (约 {rows:,} 行) {comment}")

            table_info = {
                'name': tname,
                'rows': rows,
                'comment': comment,
                'columns': []
            }

            for col in cols:
                col_info = {
                    'name': col['COLUMN_NAME'],
                    'type': col['DATA_TYPE'],
                    'nullable': col['IS_NULLABLE'],
                    'key': col['COLUMN_KEY'] or '',
                    'comment': col.get('COLUMN_COMMENT', '') or ''
                }
                table_info['columns'].append(col_info)
                flags = []
                if col_info['key']:
                    flags.append(f"🔑{col_info['key']}")
                col_str = f"      {col_info['name']:30s} {col_info['type']:12s}"
                if flags:
                    col_str += f"  {', '.join(flags)}"
                if col_info['comment']:
                    col_str += f"  # {col_info['comment']}"
                print(col_str)

            schema['tables'].append(table_info)

        # Save schema to file
        output_dir = os.path.join(os.path.dirname(__file__), '..', 'output')
        os.makedirs(output_dir, exist_ok=True)
        schema_path = os.path.join(output_dir, f"schema_{db_name}_{datetime.now().strftime('%Y%m%d')}.json")
        with open(schema_path, 'w', encoding='utf-8') as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)
        print(f"\n  💾 Schema 已保存: {schema_path}")

        return schema

    finally:
        conn.close()

if __name__ == '__main__':
    import sys

    databases = ['btyc', 'btyc_statics', 'dev_btyc', 'manage_backend', 'schedule', 'schedule2']

    if len(sys.argv) > 1:
        target = sys.argv[1]
        if target in databases:
            databases = [target]
        else:
            print(f"未知数据库: {target}")
            print(f"可用: {', '.join(databases)}")
            sys.exit(1)

    for db in databases:
        explore_database(db)
