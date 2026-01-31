with open('.env', 'r', encoding='utf-8') as f:
    lines = f.readlines()
    for i, line in enumerate(lines[13:18], start=14):
        print(f'{i}: {repr(line)}')
