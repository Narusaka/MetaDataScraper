#!/usr/bin/env python3
"""
文件名清理工具
从文件名中提取干净的标题，去掉年份和剧集编号等信息

使用示例:
python cleanup_filename.py "夫妇交欢～回不去的夜晚～ (2023)"
python cleanup_filename.py "雌吹 (2024).S01E02"
"""

import re
import sys
from typing import Optional


def clean_filename(filename: str) -> str:
    """
    清理文件名，去掉年份、剧集编号等信息

    Args:
        filename: 原始文件名

    Returns:
        清理后的文件名
    """
    # 移除文件扩展名
    name = filename
    if '.' in name:
        # 找到最后一个点之前的内容（可能是文件扩展名）
        parts = name.rsplit('.', 1)
        if len(parts) == 2 and len(parts[1]) <= 4:  # 简单的扩展名检查
            name = parts[0]

    # 定义要移除的模式
    patterns = [
        # 年份模式 (2023), (2024)等
        r'\s*\(\d{4}\)',
        # 剧集编号模式 S01E02, S1E2, Season 1 Episode 2等
        r'\s*\.?[sS]\d+[eE]\d+',
        r'\s*\.?[sS]eason\s*\d+\s*[eE]pisode\s*\d+',
        # 其他常见的编号模式
        r'\s*\[.*?\]',  # 中括号内容
        r'\s*【.*?】',  # 中文括号内容
    ]

    for pattern in patterns:
        name = re.sub(pattern, '', name, flags=re.IGNORECASE)

    # 清理多余的空格和标点
    name = re.sub(r'\s+', ' ', name)  # 将多个空格替换为单个空格
    name = name.strip(' \t\n\r\f\v.')  # 移除开头和结尾的空格及点号

    # 清理结果
    name = name.strip()

    return name


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print(__doc__)
        print("\n错误: 请提供文件名参数")
        sys.exit(1)

    input_filename = sys.argv[1]
    cleaned_name = clean_filename(input_filename)

    print(f"原始文件名: {input_filename}")
    print(f"清理后名称: {cleaned_name}")


if __name__ == "__main__":
    main()
