import logging
import re

import mysql.connector
from config_loader import database_config

MYSQL_CONNECTION_STRING = 'mysql://{user}:{password}@{host}'

db_user = database_config.get('user')
db_password = database_config.get('password')
db_host = database_config.get('host')
archive_host = database_config.get('archive_host')

source_mysql_connection = mysql.connector.connect(host=db_host, user=db_user, password=db_password)
source_mysql_cursor = source_mysql_connection.cursor(dictionary=True)

dest_mysql_connection = mysql.connector.connect(host=archive_host, user=db_user, password=db_password)
dest_mysql_cursor = dest_mysql_connection.cursor(dictionary=True)


def create_archive_database(db_name, archive_db_name):
    dest_mysql_cursor.execute(
        f'SELECT SCHEMA_NAME '
        f'FROM INFORMATION_SCHEMA.SCHEMATA '
        f'WHERE SCHEMA_NAME = \'{archive_db_name}\''
    )
    result = dest_mysql_cursor.fetchone()

    if result is None:
        source_mysql_cursor.execute(f'SHOW CREATE DATABASE {db_name}')
        create_db_query = source_mysql_cursor.fetchone()['Create Database']
        create_archive_db_query = re.sub(
            r'(?s)(CREATE DATABASE )(`.*?)(`)',
            r'\1IF NOT EXISTS `' + archive_db_name + '`',
            create_db_query,
            count=1
        )
        dest_mysql_cursor.execute(create_archive_db_query)
        logging.info(f'Created archive database {archive_db_name}')


def create_archive_table(db_name, table_name, archive_db_name,
                         archive_table_name):
    source_mysql_cursor.execute(f'USE {db_name}')
    source_mysql_cursor.execute(f'SHOW CREATE TABLE {table_name}')
    create_table_query = source_mysql_cursor.fetchone()['Create Table']

    create_archive_table_query_list = []
    for line in create_table_query.splitlines():
        if 'CREATE TABLE' in line:
            # replacing table_name with table_name_archive
            # in CREATE TABLE query
            create_archive_table_query_list.append(
                re.sub(
                    r'(?s)(CREATE TABLE )(`.*?)(`)',
                    r'\1`' + archive_table_name + '`',
                    line,
                    count=1
                )
            )
        elif 'PRIMARY KEY' in line:
            result = re.search('PRIMARY KEY \((.*)\)', line)
            primary_keys = result.group(1).split(',')
            if not len(primary_keys) > 1:
                create_archive_table_query_list.append(line)
        elif not re.search('CONSTRAINT(.*)FOREIGN KEY(.*)REFERENCES', line):
            create_archive_table_query_list.append(line)

    line_count = len(create_archive_table_query_list)
    remove_comma_line_no = line_count - 2
    remove_comma_line = create_archive_table_query_list[remove_comma_line_no]
    remove_comma_line = remove_comma_line.rstrip(',')
    create_archive_table_query_list[remove_comma_line_no] = remove_comma_line
    create_archive_table_query = ' '.join(create_archive_table_query_list)

    dest_mysql_cursor.execute(f'USE {archive_db_name}')
    dest_mysql_cursor.execute(create_archive_table_query)
    logging.info(
        f'Created archive table {archive_db_name}.{archive_table_name}')


def drop_archive_table(archive_db_name, archive_table_name):
    dest_mysql_cursor.execute(f'USE {archive_db_name}')
    dest_mysql_cursor.execute(f'DROP TABLE {archive_table_name}')
    logging.info('')
    logging.info('')
    logging.info(f'Dropped archive table {archive_db_name}.{archive_table_name}')


def get_count_of_rows_archived(archive_db_name, archive_table_name):
    dest_mysql_cursor.execute(
        f'SELECT count(*) as count '
        f'FROM {archive_db_name}.{archive_table_name}'
    )

    return dest_mysql_cursor.fetchone()['count']


def get_file_names(db_name, table_name, archive_db_name, archive_table_name,
                   column_name, where_clause):

    dest_mysql_cursor.execute(
        f'SELECT {column_name} as first_val '
        f'FROM {archive_db_name}.{archive_table_name} '
        f'ORDER BY {column_name} '
        f'LIMIT 1'
    )
    first_val = dest_mysql_cursor.fetchone()['first_val']
    first_val = str(first_val)

    dest_mysql_cursor.execute(
        f'SELECT {column_name} as last_val '
        f'FROM {archive_db_name}.{archive_table_name} '
        f'ORDER BY {column_name} DESC '
        f'LIMIT 1'
    )
    last_val = dest_mysql_cursor.fetchone()['last_val']
    last_val = str(last_val)

    data_part_name = f'({column_name})_from_({first_val})_to_({last_val})'
    s3_path = f'{db_name}/{table_name}/{data_part_name}_where_({where_clause}).csv'
    local_file_name = f'{table_name}_{data_part_name}.csv'

    return local_file_name, s3_path
