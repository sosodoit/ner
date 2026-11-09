# 사전 업데이트 시 refer_data.py 실행 필요
import pandas as pd
from pathlib import Path
from .error_stats import build_error_stat

analysis_dir = Path(__file__).resolve().parents[3] / "analysis"
analysis_dir.mkdir(parents=True, exist_ok=True)

dict_path = analysis_dir / "NER_오태깅사전.xlsx"
error_data_path = analysis_dir / "NER_개체명검수이력_V2.xlsx"

# 오태깅 사전
mistag_data = pd.read_excel(
    dict_path,
    sheet_name="오태깅목록",
    usecols="D,F:G"
)
mistag_data.columns = ["pattern", "rule_id", "sub_rule_id"]

# 태깅 사전
tag_data = pd.read_excel(
    dict_path,
    sheet_name="태깅목록",
    usecols="D,F:G"
)
tag_data.columns = ["pattern", "rule_id", "sub_rule_id"]

# 오류 이력
error_data = build_error_stat(error_data_path)

# 저장
tag_data.to_pickle(analysis_dir / "tag_data.pkl")
mistag_data.to_pickle(analysis_dir / "mistag_data.pkl")
error_data.to_pickle(analysis_dir / "error_data.pkl")
