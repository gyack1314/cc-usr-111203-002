"""显示已有原始摘要或完整热浪分析，来源文件保持不动。"""
import argparse
import json
from .io import load
from .domain import summarize
from .reading import load_dataset
from .analysis import analyze

def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['inspect','analyze']);parser.add_argument('file');a=parser.parse_args()
    if a.command=='inspect':
        v,digest=load(a.file)
        print(json.dumps({'source_sha256':digest,'summary':summarize(v)},ensure_ascii=False,indent=2,allow_nan=False))
    else:
        ds=load_dataset(a.file)
        out={'source_sha256':ds['source_sha256']};out.update(analyze(ds))
        print(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False))
if __name__=='__main__':main()
