import csv
from src.config.settings import ARTIFACTS


def safe_cell(value):
    if isinstance(value, str) and (value.lstrip().startswith(('=', '+', '-', '@'))
                                   or value.startswith(('\t', '\r', '\n'))):
        return "'" + value
    return value


def write_report(run_id, attempt, result):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    name = f'analysis-{run_id}-{attempt}.csv'
    path = ARTIFACTS / name
    staging = path.with_suffix('.tmp')
    with staging.open('w', encoding='utf-8-sig', newline='') as output:
        writer = csv.writer(output)
        writer.writerow([safe_cell(result['headline'])])
        writer.writerow([safe_cell(result.get('note', ''))])
        for metric in result['metrics']:
            writer.writerow([safe_cell(metric['label']), safe_cell(metric['value']), safe_cell(metric.get('detail', ''))])
        for table in result['tables']:
            writer.writerow([])
            writer.writerow([safe_cell(table['title'])])
            columns = table['columns']
            writer.writerow([safe_cell(column['label']) for column in columns])
            writer.writerows([safe_cell(row.get(column['key'])) for column in columns] for row in table['rows'])
    staging.replace(path)
    return name


def write_publication(publication_id, dataset_name, table):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    name = f'partner-{publication_id}.csv'
    path = ARTIFACTS / name
    staging = path.with_suffix('.tmp')
    labels = {'day': '按日', 'week': '按周', 'period': '整段'}
    with staging.open('w', encoding='utf-8-sig', newline='') as output:
        writer = csv.writer(output)
        writer.writerow([safe_cell(f'合作方工时导出 · {dataset_name}')])
        writer.writerow([safe_cell(f"粒度：{labels[table['granularity']]} · 范围 {table['start']} 至 {table['end']} · 仅统计已完工讲座")])
        writer.writerow(['日期段', '工单数', '实耗分钟', '说明'])
        for row in table['rows'] + [table['total']]:
            writer.writerow([safe_cell(row['label']), row['count'],
                             row['minutes'] if row['minutes'] is not None else '已隐藏',
                             safe_cell(row.get('reason') or '')])
        writer.writerow([])
        writer.writerow([safe_cell('注：只有一两单的日期段不展示精确实耗；本批次全部已发表格已联合校验，无法据此反推这些段的实耗。')])
    staging.replace(path)
    return name
