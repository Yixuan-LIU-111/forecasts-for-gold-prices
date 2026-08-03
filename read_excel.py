
import pandas as pd

file_path = 'docs/黄金价格影响因素细化表.xlsx'
xls = pd.ExcelFile(file_path)

sheets = xls.sheet_names
print('=== 所有Sheet名称 ===')
for sheet in sheets:
    print(f'- {sheet}')

for sheet_name in sheets:
    df = pd.read_excel(file_path, sheet_name=sheet_name)
    print(f'\n=== Sheet: {sheet_name} ===')
    print(f'行数: {df.shape[0]}, 列数: {df.shape[1]}')
    print('列名:', df.columns.tolist())
    print('\n数据内容:')
    pd.set_option('display.max_columns', None)
    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_colwidth', None)
    print(df.to_string())
    print('\n' + '='*80 + '\n')
