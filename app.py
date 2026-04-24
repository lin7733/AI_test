
import hashlib
import json
import random
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from PIL import Image, ImageFile
import streamlit as st

ImageFile.LOAD_TRUNCATED_IMAGES = True

st.set_page_config(
    page_title="AI辅助质检实验平台",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="collapsed",
)

BASE_DIR = Path(__file__).resolve().parent
WORKBOOK_FILENAME = "AI_质检实验题库_实验一实验二_多目标采购版.xlsx"
DATASET_ROOT = BASE_DIR / "00_raw"
RESULTS_DIR_DEFAULT = BASE_DIR / "results"

APP_TITLE = "AI辅助质检实验平台"
BREAK_AFTER = 24
OUTPUT_XLSX_NAME = "experiment_data.xlsx"

CONSENT_TEXT = """
**知情同意书**

本实验为本科毕业论文研究项目，研究主题为“AI 辅助决策中解释透明度与依赖行为”。

**实验内容：**
你将完成一系列工业产品判断任务，并在实验结束后填写简短问卷。

**数据使用：**
实验过程中记录的作答结果、反应时间和问卷评分，仅用于学术研究分析。

**自愿参与：**
你可以在任何时候选择退出实验，不会产生任何不良后果。

**实验时长：**
约 20–30 分钟。

请确认你已充分理解以上内容，并自愿参与本实验。
"""

PRODUCT_STANDARDS = {
    "bottle": {
        "name": "瓶子（Bottle）",
        "ok": "瓶身表面完整光滑，无可见污渍、破损或异物附着。",
        "ng_types": [
            "污染（Contamination）：瓶身表面有污渍、附着物或颜色异常区域",
            "大破损（Broken Large）：瓶口、瓶身出现较大缺口或破裂",
            "小破损（Broken Small）：瓶身出现细微裂缝或小缺口",
        ],
    },
    "capsule": {
        "name": "胶囊（Capsule）",
        "ok": "胶囊外壳完整，颜色均匀，无变形、裂缝或内容物渗漏。",
        "ng_types": [
            "裂缝（Crack）：胶囊壳体出现裂纹或断裂",
            "渗漏（Squeeze）：胶囊受挤压变形或内容物外漏",
            "压痕（Poke）：胶囊表面有明显凹陷或戳痕",
            "划痕（Scratch）：胶囊表面有线状划伤痕迹",
        ],
    },
    "metal_nut": {
        "name": "金属螺母（Metal Nut）",
        "ok": "螺母形状规则，颜色均匀，螺纹完整，无弯曲、翻转或划痕。",
        "ng_types": [
            "弯曲（Bent）：螺母出现变形或弯曲",
            "颜色异常（Color）：螺母表面颜色不均匀或有锈斑",
            "翻转（Flip）：螺母放置方向错误或翻面",
            "划痕（Scratch）：螺母表面有明显划伤",
        ],
    },
}


def safe_str(v) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip()


def stable_hash_int(text: str) -> int:
    return int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)


def sanitize_for_path(text: str) -> str:
    cleaned = "".join(ch for ch in safe_str(text) if ch.isalnum() or ch in {"_", "-"})
    return cleaned or "unknown"


def build_participant_id(student_id: str, exp_short: str) -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{exp_short}_{sanitize_for_path(student_id)}_{ts}"


def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [safe_str(c) for c in df.columns]
    for c in df.columns:
        df[c] = df[c].apply(safe_str)
    return df


def find_workbook_path() -> Path:
    candidates = [
        BASE_DIR / "05_metadata" / WORKBOOK_FILENAME,
        BASE_DIR / WORKBOOK_FILENAME,
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return p

    metadata_dir = BASE_DIR / "05_metadata"
    if metadata_dir.exists():
        dir_listing = "\n".join(sorted(x.name for x in metadata_dir.iterdir()))
    else:
        dir_listing = "<05_metadata 文件夹不存在>"

    searched = "\n".join(str(p) for p in candidates)
    raise FileNotFoundError(
        "未找到题库文件。\n已搜索路径：\n"
        f"{searched}\n\n"
        "05_metadata 目录内容：\n"
        f"{dir_listing}"
    )


def read_structured_sheet(workbook_path: str, sheet_name: str) -> pd.DataFrame:
    raw = pd.read_excel(workbook_path, sheet_name=sheet_name, header=None)
    header_row_idx = None
    for idx in range(min(5, len(raw))):
        row_values = [safe_str(x) for x in raw.iloc[idx].tolist()]
        if "题号" in row_values or "练习题号" in row_values:
            header_row_idx = idx
            break
    if header_row_idx is None:
        raise ValueError(f"{sheet_name} 未找到表头行。")

    headers = [safe_str(x) for x in raw.iloc[header_row_idx].tolist()]
    data = raw.iloc[header_row_idx + 1 :].copy()
    data.columns = headers
    data = data.dropna(how="all")
    data = normalize_df(data)
    if headers[0] in data.columns:
        data = data[data[headers[0]] != ""]
    return data.reset_index(drop=True)


def to_int(value, default=0):
    try:
        if safe_str(value) == "":
            return default
        return int(float(value))
    except Exception:
        return default


def to_float(value, default=0.0):
    try:
        if safe_str(value) == "":
            return default
        return float(value)
    except Exception:
        return default


def normalize_category(value: str) -> str:
    text = safe_str(value).lower()
    mapping = {
        "bottle": "bottle",
        "capsule": "capsule",
        "metal_nut": "metal_nut",
        "瓶": "bottle",
        "胶囊": "capsule",
        "螺母": "metal_nut",
    }
    for key, val in mapping.items():
        if key in text:
            return val
    return safe_str(value)


def normalize_complexity(value: str) -> str:
    text = safe_str(value).lower()
    if "low" in text or "低" in text:
        return "low"
    if "high" in text or "高" in text:
        return "high"
    return safe_str(value)


def normalize_okng_label(value: str) -> str:
    text = safe_str(value).lower().replace("（", "(").replace("）", ")")
    if any(k in text for k in ["ok", "合格", "正常", "good", "无缺陷", "no defect"]):
        return "OK"
    if any(k in text for k in ["ng", "不合格", "缺陷", "异常", "bad", "defect"]):
        return "NG"
    return safe_str(value)


def okng_code(value: str) -> int:
    return 1 if normalize_okng_label(value) == "OK" else 0


def normalize_purchase_label(value: str) -> str:
    text = safe_str(value)
    if text in {"1", "采购", "建议采购", "buy", "BUY"}:
        return "采购"
    if text in {"0", "不采购", "建议不采购", "not_buy", "NO_BUY"}:
        return "不采购"
    return text


def purchase_code(value: str) -> int:
    text = safe_str(value)
    if text in {"1", "采购", "建议采购", "buy", "BUY"}:
        return 1
    if text in {"0", "不采购", "建议不采购", "not_buy", "NO_BUY"}:
        return 0
    return 0


def parse_ai_correct(value: str, fallback=None) -> int:
    text = safe_str(value).lower()
    if any(k in text for k in ["正确", "true", "yes", "是", "1"]):
        return 1
    if any(k in text for k in ["错误", "false", "no", "否", "0"]):
        return 0
    return 1 if fallback else 0


def decision_is_correct(decision_code: int, true_code: int) -> int:
    return int(decision_code == true_code)


def calc_dependence(adopted: int, ai_correct: int) -> str:
    if ai_correct == 1:
        return "proper" if adopted == 1 else "under"
    return "over" if adopted == 1 else "proper"


def resolve_image_path(raw_path: str) -> Path:
    if not raw_path:
        raise FileNotFoundError("题库中未提供图片路径。")

    raw_norm = safe_str(raw_path).replace("\\", "/")
    root = Path(DATASET_ROOT)
    direct = Path(raw_norm)
    candidates = []

    def add_candidate(path_obj: Path):
        if path_obj not in candidates:
            candidates.append(path_obj)

    add_candidate(direct)
    add_candidate(root / raw_norm)

    if "00_raw/" in raw_norm:
        rel = raw_norm.split("00_raw/", 1)[1]
        add_candidate(root / rel)

    parts = [p for p in raw_norm.split("/") if p]
    for key in ["bottle", "capsule", "metal_nut"]:
        if key in parts:
            idx = parts.index(key)
            add_candidate(root / Path(*parts[idx:]))
            break

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    filename = Path(raw_norm).name
    if filename and root.exists():
        matches = list(root.rglob(filename))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raw_lower = raw_norm.lower()
            for match in matches:
                match_str = str(match).replace("\\", "/").lower()
                if all(seg.lower() in match_str for seg in parts[-3:]):
                    return match
            return matches[0]

    raise FileNotFoundError(
        f"图片未找到：{raw_path}。\n请检查图片路径是否仍为 TO_FILL 占位路径，或当前 00_raw 目录是否与题库一致。"
    )


def ensure_results_dir(participant_id: str) -> Path:
    out_dir = Path(RESULTS_DIR_DEFAULT) / participant_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def save_json(path: Path, payload: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def map_strategy_code(text: str) -> str:
    mapping = {
        "主要依靠自己的图像判断": "self",
        "图像判断和AI建议各参考一半": "half",
        "主要参考AI建议": "ai",
        "视情况而定": "depends",
        "主要看质量，再兼顾成本": "quality_first",
        "质量与成本大致各占一半": "balanced",
        "主要看成本，只要质量别太差": "cost_first",
    }
    return mapping.get(text, safe_str(text))


def map_changed_reason_code(text: str) -> str:
    mapping = {
        "AI建议与我不同，选择相信AI": "trust_ai",
        "AI的解释让我重新审视图像": "recheck_image",
        "不确定时偏向跟随AI": "uncertain_follow_ai",
        "我没有改变过判断": "no_change",
        "看到价格后改变了判断": "price_changed",
        "看到质量信息后改变了判断": "quality_changed",
    }
    return mapping.get(text, safe_str(text))


def load_all_banks():
    workbook_path = find_workbook_path()
    try:
        exp1_df = read_structured_sheet(workbook_path, "题库总表")
        exp2_df = read_structured_sheet(workbook_path, "Exp2_多目标采购")
        practice_df = read_structured_sheet(workbook_path, "Practice")
    except Exception as e:
        st.error(f"题库读取失败：{e}")
        return workbook_path, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    return workbook_path, exp1_df, exp2_df, practice_df


def build_exp1_trials(df: pd.DataFrame, participant_key: str):
    condition = "有解释" if stable_hash_int(participant_key) % 2 == 0 else "无解释"
    trials = []
    for _, row in df.iterrows():
        trials.append(
            {
                "task_type": "exp1",
                "trial_id": safe_str(row.get("题号")),
                "item_id": safe_str(row.get("图片ID")),
                "category": safe_str(row.get("产品类别")),
                "defect_type": safe_str(row.get("缺陷类型")),
                "complexity": safe_str(row.get("复杂度代码") or row.get("复杂度")),
                "true_label": normalize_okng_label(row.get("真实标签")),
                "true_code": to_int(row.get("真实标签代码"), okng_code(row.get("真实标签"))),
                "ai_label": normalize_okng_label(row.get("AI建议")),
                "ai_code": to_int(row.get("AI建议代码"), okng_code(row.get("AI建议"))),
                "ai_correct": parse_ai_correct(
                    row.get("AI是否正确"),
                    fallback=okng_code(row.get("AI建议")) == okng_code(row.get("真实标签")),
                ),
                "image_path": safe_str(row.get("图片源路径")),
                "explanation_mode": "unified" if condition == "有解释" else "none",
                "explanation_text": safe_str(row.get("实验一-统一解释内容")) if condition == "有解释" else "",
                "exp_name": "实验一",
                "ui_decision_labels": ("OK", "NG"),
                "feedback_text": "",
            }
        )
    rnd = random.Random(stable_hash_int(participant_key + "_exp1_order"))
    rnd.shuffle(trials)
    return trials, {"exp_name": "实验一", "design": "between", "condition": "with_expl" if condition == "有解释" else "no_expl"}


def build_exp2_trials(df: pd.DataFrame, participant_key: str):
    trials = []
    for _, row in df.iterrows():
        trials.append(
            {
                "task_type": "exp2",
                "trial_id": safe_str(row.get("题号")),
                "item_id": safe_str(row.get("图片ID")),
                "category": safe_str(row.get("产品类别")),
                "defect_type": safe_str(row.get("缺陷类型")),
                "complexity": safe_str(row.get("复杂度代码") or row.get("复杂度")),
                "image_path": safe_str(row.get("图片源路径")),
                "quality_score": to_float(row.get("quality_score")),
                "supplier_price": to_float(row.get("supplier_price")),
                "cost_score": to_float(row.get("cost_score")),
                "quality_gate": to_float(row.get("quality_gate")),
                "weighted_score": to_float(row.get("weighted_score")),
                "purchase_threshold": to_float(row.get("purchase_threshold")),
                "true_label": normalize_purchase_label(row.get("purchase_gt_label")),
                "true_code": to_int(row.get("purchase_gt_code"), purchase_code(row.get("purchase_gt_label"))),
                "ai_label": normalize_purchase_label(row.get("ai_suggestion_label")),
                "ai_code": to_int(row.get("ai_suggestion_code"), purchase_code(row.get("ai_suggestion_label"))),
                "ai_correct": to_int(row.get("ai_correct_code"), parse_ai_correct(row.get("ai_correct_label"))),
                "decision_zone": safe_str(row.get("decision_zone")),
                "suggestion_type": safe_str(row.get("suggestion_type")),
                "explanation_mode": "reason",
                "explanation_text": safe_str(row.get("实验二-理由型解释内容")),
                "exp_name": "实验二",
                "ui_decision_labels": ("采购", "不采购"),
                "feedback_text": "",
            }
        )
    rnd = random.Random(stable_hash_int(participant_key + "_exp2_order"))
    rnd.shuffle(trials)
    return trials, {"exp_name": "实验二", "design": "single_task", "condition": "multi_objective_purchase"}


def build_practice_trials(practice_df: pd.DataFrame, exp_name: str):
    filtered = practice_df[practice_df["适用实验"] == exp_name].copy().reset_index(drop=True)
    trials = []
    for _, row in filtered.iterrows():
        task_type = "exp1" if exp_name == "实验一" else "exp2"
        if task_type == "exp1":
            trials.append(
                {
                    "task_type": "exp1",
                    "trial_id": safe_str(row.get("练习题号")),
                    "item_id": safe_str(row.get("图片ID")),
                    "category": safe_str(row.get("产品类别")),
                    "defect_type": safe_str(row.get("缺陷类型")),
                    "complexity": safe_str(row.get("复杂度")),
                    "true_label": normalize_okng_label(row.get("标准答案")),
                    "true_code": to_int(row.get("标准答案代码"), okng_code(row.get("标准答案"))),
                    "ai_label": normalize_okng_label(row.get("AI建议")),
                    "ai_code": to_int(row.get("AI建议代码"), okng_code(row.get("AI建议"))),
                    "ai_correct": int(
                        to_int(row.get("AI建议代码"), okng_code(row.get("AI建议")))
                        == to_int(row.get("标准答案代码"), okng_code(row.get("标准答案")))
                    ),
                    "image_path": safe_str(row.get("图片源路径")),
                    "explanation_mode": "none",
                    "explanation_text": "",
                    "exp_name": "实验一",
                    "ui_decision_labels": ("OK", "NG"),
                    "feedback_text": safe_str(row.get("反馈文本")),
                    "is_practice": True,
                }
            )
        else:
            feedback_text = safe_str(row.get("反馈文本"))
            trials.append(
                {
                    "task_type": "exp2",
                    "trial_id": safe_str(row.get("练习题号")),
                    "item_id": safe_str(row.get("图片ID")),
                    "category": safe_str(row.get("产品类别")),
                    "defect_type": safe_str(row.get("缺陷类型")),
                    "complexity": safe_str(row.get("复杂度")),
                    "image_path": safe_str(row.get("图片源路径")),
                    "quality_score": 0.0,
                    "supplier_price": 0.0,
                    "cost_score": 0.0,
                    "quality_gate": 0.0,
                    "weighted_score": 0.0,
                    "purchase_threshold": 0.0,
                    "true_label": normalize_purchase_label(row.get("标准答案")),
                    "true_code": to_int(row.get("标准答案代码"), purchase_code(row.get("标准答案"))),
                    "ai_label": normalize_purchase_label(row.get("AI建议")),
                    "ai_code": to_int(row.get("AI建议代码"), purchase_code(row.get("AI建议"))),
                    "ai_correct": int(
                        to_int(row.get("AI建议代码"), purchase_code(row.get("AI建议")))
                        == to_int(row.get("标准答案代码"), purchase_code(row.get("标准答案")))
                    ),
                    "decision_zone": "",
                    "suggestion_type": "",
                    "explanation_mode": "reason",
                    "explanation_text": "",
                    "exp_name": "实验二",
                    "ui_decision_labels": ("采购", "不采购"),
                    "feedback_text": feedback_text,
                    "practice_task_type": safe_str(row.get("任务类型")),
                    "is_practice": True,
                }
            )
    return trials


def participant_sheet_df() -> pd.DataFrame:
    meta = st.session_state.get("participant_meta", {})
    exp_meta = st.session_state.get("exp_meta", {})
    workbook_path = st.session_state.get("workbook_path", "")
    if not meta:
        return pd.DataFrame()
    row = {
        "participant_id": meta.get("participant_id", ""),
        "name": meta.get("name", ""),
        "student_id": meta.get("student_id", ""),
        "age": meta.get("age", ""),
        "gender": meta.get("gender", ""),
        "major": meta.get("major", ""),
        "exp_type": meta.get("exp_type", ""),
        "exp_condition": meta.get("exp_condition", ""),
        "design": exp_meta.get("design", ""),
        "workbook_path": workbook_path,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    return pd.DataFrame([row])


def questionnaire_sheet_df() -> pd.DataFrame:
    q = st.session_state.get("questionnaire", {})
    meta = st.session_state.get("participant_meta", {})
    if not q or not meta:
        return pd.DataFrame()
    row = {"participant_id": meta.get("participant_id", "")}
    row.update(q)
    return pd.DataFrame([row])


def trial_sheet_df() -> pd.DataFrame:
    rows = st.session_state.get("responses", [])
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def save_progress():
    meta = st.session_state.get("participant_meta", {})
    if not meta:
        return
    out_dir = ensure_results_dir(meta.get("participant_id", "unknown"))
    xlsx_path = out_dir / OUTPUT_XLSX_NAME

    participant_df = participant_sheet_df()
    questionnaire_df = questionnaire_sheet_df()
    trial_df = trial_sheet_df()

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        participant_df.to_excel(writer, sheet_name="participant_info", index=False)
        (questionnaire_df if not questionnaire_df.empty else pd.DataFrame(columns=["participant_id"])).to_excel(
            writer, sheet_name="questionnaire", index=False
        )
        (trial_df if not trial_df.empty else pd.DataFrame(columns=["participant_id", "trial_id"])).to_excel(
            writer, sheet_name="trial_data", index=False
        )

    save_json(
        out_dir / "session_meta.json",
        {
            "participant_meta": meta,
            "exp_meta": st.session_state.get("exp_meta", {}),
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "xlsx_path": str(xlsx_path),
        },
    )


def init_session():
    defaults = {
        "stage": "setup",
        "workbook_path": "",
        "participant_meta": {},
        "exp_meta": {},
        "trials": [],
        "practice_trials": [],
        "current_index": 0,
        "current_render_id": None,
        "trial_start_ts": None,
        "exp_start_ts": None,
        "responses": [],
        "questionnaire": {},
        "rest_done": False,
        "trial_phase": "initial",
        "initial_decision_label": None,
        "initial_decision_code": None,
        "initial_rt_ms": None,
        "resolved_image_path": "",
        "show_debug": False,
        "show_practice_feedback": False,
        "practice_feedback_text": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def reset_experiment():
    for key in list(st.session_state.keys()):
        if key in {
            "stage", "workbook_path", "participant_meta", "exp_meta", "trials", "practice_trials",
            "current_index", "current_render_id", "trial_start_ts", "exp_start_ts", "responses",
            "questionnaire", "rest_done", "trial_phase", "initial_decision_label", "initial_decision_code",
            "initial_rt_ms", "resolved_image_path", "show_debug", "show_practice_feedback", "practice_feedback_text"
        }:
            del st.session_state[key]
    init_session()


def render_setup(exp1_df: pd.DataFrame, exp2_df: pd.DataFrame, practice_df: pd.DataFrame):
    st.title(APP_TITLE)
    st.info(
        "**参与须知：** 本实验分为实验一和实验二两种类型，**每位被试只需完成其中一种**。"
        "请根据研究者安排选择实验类型，并如实填写以下基本信息。"
    )

    workbook_path = st.session_state.get("workbook_path", "") or find_workbook_path()
    st.caption(f"当前题库文件：{workbook_path}")

    with st.form("setup_form"):
        st.markdown("#### 被试基本信息")
        c1, c2, c3 = st.columns(3)
        with c1:
            name = st.text_input("姓名 *")
            student_id = st.text_input("学号 *")
        with c2:
            age = st.text_input("年龄 *")
            gender = st.selectbox("性别 *", ["", "女", "男"])
        with c3:
            major = st.text_input("专业 *")
            exp_name = st.selectbox("实验类型 *", ["实验一：有无解释（质检判断）", "实验二：多目标采购判断"])

        submitted = st.form_submit_button("确认并进入实验", use_container_width=True, type="primary")

    if submitted:
        errors = []
        if not safe_str(name):
            errors.append("姓名")
        if not safe_str(student_id):
            errors.append("学号")
        if not safe_str(age):
            errors.append("年龄")
        if not gender:
            errors.append("性别")
        if not safe_str(major):
            errors.append("专业")
        if errors:
            st.error(f"请填写以下必填项：{'、'.join(errors)}")
            return

        exp_short = "exp1" if exp_name.startswith("实验一") else "exp2"
        participant_id = build_participant_id(student_id, exp_short)
        participant_key = safe_str(student_id) or participant_id

        if exp_short == "exp1":
            if exp1_df.empty:
                st.error("实验一题库未成功加载。")
                return
            trials, meta = build_exp1_trials(exp1_df, participant_key)
            practice_trials = build_practice_trials(practice_df, "实验一")
            exp_condition = meta.get("condition", "")
        else:
            if exp2_df.empty:
                st.error("实验二题库未成功加载。")
                return
            trials, meta = build_exp2_trials(exp2_df, participant_key)
            practice_trials = build_practice_trials(practice_df, "实验二")
            exp_condition = meta.get("condition", "")

        st.session_state["participant_meta"] = {
            "participant_id": participant_id,
            "name": safe_str(name),
            "student_id": safe_str(student_id),
            "age": safe_str(age),
            "gender": gender,
            "major": safe_str(major),
            "exp_type": exp_short,
            "exp_condition": exp_condition,
        }
        st.session_state["exp_meta"] = meta
        st.session_state["trials"] = trials
        st.session_state["practice_trials"] = practice_trials
        st.session_state["current_index"] = 0
        st.session_state["responses"] = []
        st.session_state["questionnaire"] = {}
        st.session_state["rest_done"] = False
        st.session_state["exp_start_ts"] = None
        st.session_state["show_practice_feedback"] = False
        st.session_state["practice_feedback_text"] = ""
        save_progress()
        st.session_state["stage"] = "consent"
        st.rerun()

    with st.expander("查看题库摘要（研究者用）", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**实验一题量**")
            if not exp1_df.empty:
                st.dataframe(
                    exp1_df.groupby(["产品类别", "复杂度"]).size().reset_index(name="数量"),
                    hide_index=True,
                    use_container_width=True,
                )
        with c2:
            st.markdown("**实验二题量**")
            if not exp2_df.empty:
                st.dataframe(
                    exp2_df.groupby(["产品类别", "复杂度", "suggestion_type"]).size().reset_index(name="数量"),
                    hide_index=True,
                    use_container_width=True,
                )


def render_consent():
    st.title("知情同意")
    st.markdown(CONSENT_TEXT)
    agree = st.checkbox("我已仔细阅读以上内容，自愿参加本实验。")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("返回上一页", use_container_width=True):
            st.session_state["stage"] = "setup"
            st.rerun()
    with c2:
        if st.button("同意并继续", type="primary", use_container_width=True, disabled=not agree):
            st.session_state["stage"] = "instruction"
            st.rerun()


def render_instruction():
    exp_type = st.session_state.get("participant_meta", {}).get("exp_type", "exp1")
    st.title("实验说明")

    if exp_type == "exp1":
        st.markdown("---")
        st.markdown("### 一、实验任务")
        st.markdown(
            """
你将看到一系列工业产品图像，每张图片展示的是 **瓶子、胶囊或金属螺母** 之一。
你的任务是判断图中产品是否合格：

| 判定 | 含义 |
|------|------|
| ✅ **OK（合格）** | 产品外观无明显缺陷，可以出厂 |
| ❌ **NG（不合格）** | 产品存在可见异常，不可出厂 |
            """
        )

        st.markdown("---")
        st.markdown("### 二、各产品合格 / 不合格标准")
        for _, info in PRODUCT_STANDARDS.items():
            with st.expander(f"📦 {info['name']}", expanded=True):
                st.markdown(f"**✅ 合格品：** {info['ok']}")
                st.markdown("**❌ 不合格品常见缺陷：**")
                for d in info["ng_types"]:
                    st.markdown(f"- {d}")

        st.markdown("---")
        st.markdown("### 三、每道题的作答流程")
        st.markdown(
            """
每道题分为 **两个步骤**：

**第一步 — 独立判断（看不到 AI 建议）**
> 请先仔细观察产品图像，根据自己的判断选择 OK 或 NG。

**第二步 — 参考 AI 后最终决策**
> 完成初步判断后，系统会显示 AI 的检测结果（部分被试会看到解释信息）。
> 请综合图像与 AI 建议，给出你的最终判断。最终判断可与初步判断相同或不同。
            """
        )
    else:
        st.markdown("---")
        st.markdown("### 一、实验任务")
        st.markdown(
            """
你将看到一系列工业产品图像，并同时获得该产品的**质量信息**与**供应价格信息**。
你的任务不是单纯判断“合格 / 不合格”，而是结合**质量**与**成本**，判断该产品是否值得采购：

| 判定 | 含义 |
|------|------|
| ✅ **采购** | 该产品整体采购价值较高，建议采购 |
| ❌ **不采购** | 该产品整体采购价值不足，不建议采购 |
            """
        )

        st.markdown("---")
        st.markdown("### 二、判断原则")
        st.markdown(
            """
- 请先关注产品质量是否达到基本要求。
- 若质量明显偏低，即使价格较低，也未必值得采购。
- 若质量基本达标，再综合考虑成本信息做出采购判断。
- 系统不会告诉你后台如何计算综合判断，请根据页面提供的信息独立决策。
            """
        )

        st.markdown("---")
        st.markdown("### 三、每道题的作答流程")
        st.markdown(
            """
每道题分为 **两个步骤**：

**第一步 — 独立判断（看不到 AI 建议）**
> 先根据图像、质量信息和供应价格，独立判断“采购”或“不采购”。

**第二步 — 参考 AI 后最终决策**
> 完成初步判断后，系统会显示 AI 的采购建议。
> 请综合你自己的判断与 AI 建议，给出最终判断。最终判断可与初步判断相同或不同。
            """
        )

    st.markdown("---")
    st.markdown(
        f"""
**⚠️ 注意事项**
- 前 **4 题** 为练习题，不计入正式数据。
- 正式实验共 **48 题**，中途会有一次短暂休息（第 {BREAK_AFTER} 题后）。
- 系统会记录你的两次判断和反应时间。
- 练习题会显示标准答案反馈，正式题不会显示。
- 实验结束后请完成问卷。
        """
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("返回知情同意", use_container_width=True):
            st.session_state["stage"] = "consent"
            st.rerun()
    with c2:
        if st.button("进入练习题", type="primary", use_container_width=True):
            st.session_state["stage"] = "practice"
            st.session_state["current_index"] = 0
            st.session_state["current_render_id"] = None
            st.rerun()


def render_rest():
    st.title("请稍作休息 ☕")
    st.markdown("你已完成前 24 题，建议休息 1–2 分钟后再继续。")
    elapsed = int(time.time() - (st.session_state.get("exp_start_ts") or time.time()))
    st.info(f"当前已用时：{elapsed // 60} 分 {elapsed % 60} 秒")
    if st.button("我已休息好，继续实验", type="primary", use_container_width=True):
        st.session_state["rest_done"] = True
        st.session_state["stage"] = "formal"
        st.session_state["current_render_id"] = None
        st.rerun()


def render_exp2_info(trial: dict, mode: str):
    st.markdown("### 当前产品信息")
    quality_score = trial.get("quality_score", 0)
    supplier_price = trial.get("supplier_price", 0)
    if mode == "practice" and quality_score == 0 and supplier_price == 0:
        st.info("本题为练习题，请结合图像与页面信息练习“采购 / 不采购”判断。")
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.metric("质量分", f"{quality_score:.0f}")
        with c2:
            st.metric("供应价格", f"{supplier_price:.1f} 元/件")


def render_practice_feedback():
    st.markdown("---")
    st.markdown("### 练习题反馈")
    st.info(st.session_state.get("practice_feedback_text", ""))
    if st.button("继续下一题", type="primary", use_container_width=True):
        st.session_state["show_practice_feedback"] = False
        st.session_state["practice_feedback_text"] = ""
        st.session_state["current_index"] += 1
        st.session_state["current_render_id"] = None
        st.session_state["trial_phase"] = "initial"
        st.rerun()


def render_trial(trials: list, mode: str):
    idx = st.session_state["current_index"]
    total = len(trials)

    if idx >= total:
        st.session_state["current_index"] = 0
        st.session_state["stage"] = "formal" if mode == "practice" else "questionnaire"
        st.session_state["current_render_id"] = None
        st.session_state["trial_phase"] = "initial"
        st.rerun()

    if mode == "formal" and idx == BREAK_AFTER and not st.session_state.get("rest_done", False):
        st.session_state["stage"] = "rest"
        st.rerun()

    trial = trials[idx]
    render_uid = f"{mode}_{trial['task_type']}_{trial['trial_id']}_{idx}"

    if st.session_state["current_render_id"] != render_uid:
        st.session_state["current_render_id"] = render_uid
        st.session_state["trial_start_ts"] = time.time()
        st.session_state["trial_phase"] = "initial"
        st.session_state["initial_decision_label"] = None
        st.session_state["initial_decision_code"] = None
        st.session_state["initial_rt_ms"] = None
        st.session_state["resolved_image_path"] = ""
        st.session_state["show_practice_feedback"] = False
        st.session_state["practice_feedback_text"] = ""

    if mode == "formal" and not st.session_state.get("exp_start_ts"):
        st.session_state["exp_start_ts"] = time.time()

    if mode == "formal":
        elapsed = int(time.time() - st.session_state["exp_start_ts"])
        em, es = elapsed // 60, elapsed % 60
        st.markdown(
            f"<div style='text-align:center;padding:6px 0;font-size:0.95rem;'>"
            f"⏱️ 已用时 <b>{em:02d}:{es:02d}</b> &nbsp;|&nbsp; 题目进度 <b>{idx + 1} / {total}</b>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.progress((idx + 1) / total)
    else:
        st.progress((idx + 1) / total, text=f"练习题进度：{idx + 1}/{total}")

    st.subheader(f"{'练习题' if mode == 'practice' else '正式题'} {idx + 1} / {total}")

    if mode == "practice" and st.session_state.get("show_practice_feedback"):
        render_practice_feedback()
        return

    phase = st.session_state.get("trial_phase", "initial")
    c1, c2 = st.columns([1.25, 1.0])

    with c1:
        try:
            img_path = resolve_image_path(trial["image_path"])
            st.session_state["resolved_image_path"] = str(img_path)
            st.image(Image.open(img_path).convert("RGB"), use_container_width=True)
            if st.session_state.get("show_debug"):
                st.caption(f"图片路径：{img_path}")
        except Exception as e:
            st.error(f"图片读取失败：{e}")

    with c2:
        if trial["task_type"] == "exp2":
            render_exp2_info(trial, mode)
            st.markdown("---")

        if phase == "initial":
            st.markdown("### 第一步：请先独立判断")
            if trial["task_type"] == "exp1":
                st.info("请仔细观察图像，在看到 AI 建议之前，先给出你的初步判断。")
            else:
                st.info("请先根据图像、质量信息和价格信息，独立判断是否采购。")

            labels = trial["ui_decision_labels"]
            col_a, col_b = st.columns(2)

            def submit_initial(label: str, code: int):
                rt = int((time.time() - st.session_state["trial_start_ts"]) * 1000)
                st.session_state["initial_decision_label"] = label
                st.session_state["initial_decision_code"] = code
                st.session_state["initial_rt_ms"] = rt
                st.session_state["trial_phase"] = "final"
                st.session_state["trial_start_ts"] = time.time()
                st.rerun()

            with col_a:
                if st.button(f"✅ {labels[0]}", key=f"i_a_{render_uid}", use_container_width=True):
                    submit_initial(labels[0], 1)
            with col_b:
                if st.button(f"❌ {labels[1]}", key=f"i_b_{render_uid}", use_container_width=True):
                    submit_initial(labels[1], 0)

            st.caption("完成初步判断后，将显示 AI 建议，再进行最终决策。")
        else:
            st.markdown("### 第二步：参考 AI 建议，做最终判断")
            st.info(f"**AI 建议：{trial['ai_label']}**")
            if safe_str(trial.get("explanation_text", "")):
                st.write(trial["explanation_text"])
            st.caption(f"你的初步判断：**{st.session_state['initial_decision_label']}**")
            st.markdown("---")
            st.markdown("**你的最终判断：**")

            labels = trial["ui_decision_labels"]
            col_a, col_b = st.columns(2)

            def submit_final(label: str, code: int):
                rt = int((time.time() - st.session_state["trial_start_ts"]) * 1000)
                init_label = st.session_state["initial_decision_label"]
                init_code = st.session_state["initial_decision_code"]
                init_rt = st.session_state["initial_rt_ms"] or 0
                meta = st.session_state["participant_meta"]
                exp_meta = st.session_state["exp_meta"]

                adopted = int(code == trial["ai_code"])

                record = {
                    "participant_id": meta.get("participant_id", ""),
                    "exp_type": meta.get("exp_type", ""),
                    "exp_condition": meta.get("exp_condition", ""),
                    "design": exp_meta.get("design", ""),
                    "task_type": trial["task_type"],
                    "trial_stage": mode,
                    "trial_index": idx + 1,
                    "trial_id": trial["trial_id"],
                    "item_id": trial["item_id"],
                    "category": normalize_category(trial["category"]),
                    "defect_type": safe_str(trial["defect_type"]),
                    "complexity": normalize_complexity(trial["complexity"]),
                    "true_label": trial["true_label"],
                    "true_code": trial["true_code"],
                    "ai_label": trial["ai_label"],
                    "ai_code": trial["ai_code"],
                    "ai_correct": trial["ai_correct"],
                    "explanation_mode": trial["explanation_mode"],
                    "initial_decision_label": init_label,
                    "initial_decision_code": init_code,
                    "final_decision_label": label,
                    "final_decision_code": code,
                    "initial_correct": decision_is_correct(init_code, trial["true_code"]),
                    "final_correct": decision_is_correct(code, trial["true_code"]),
                    "initial_rt_ms": init_rt,
                    "final_rt_ms": rt,
                    "total_rt_ms": init_rt + rt,
                    "decision_changed": int(code != init_code),
                    "adopt_ai": adopted,
                    "dependence_type": calc_dependence(adopted, trial["ai_correct"]),
                    "recorded_at": datetime.now().isoformat(timespec="seconds"),
                }

                if trial["task_type"] == "exp2":
                    record.update(
                        {
                            "quality_score": trial.get("quality_score", ""),
                            "supplier_price": trial.get("supplier_price", ""),
                            "cost_score": trial.get("cost_score", ""),
                            "quality_gate": trial.get("quality_gate", ""),
                            "weighted_score": trial.get("weighted_score", ""),
                            "purchase_threshold": trial.get("purchase_threshold", ""),
                            "decision_zone": trial.get("decision_zone", ""),
                            "suggestion_type": trial.get("suggestion_type", ""),
                        }
                    )

                if mode != "practice":
                    st.session_state["responses"].append(record)
                    save_progress()
                    st.session_state["current_index"] += 1
                    st.session_state["current_render_id"] = None
                    st.session_state["trial_phase"] = "initial"
                    st.rerun()
                else:
                    st.session_state["practice_feedback_text"] = trial.get("feedback_text", "")
                    st.session_state["show_practice_feedback"] = True
                    st.rerun()

            with col_a:
                if st.button(f"✅ {labels[0]}", key=f"f_a_{render_uid}", use_container_width=True):
                    submit_final(labels[0], 1)
            with col_b:
                if st.button(f"❌ {labels[1]}", key=f"f_b_{render_uid}", use_container_width=True):
                    submit_final(labels[1], 0)

            st.caption("点击后自动进入下一题。" if mode != "practice" else "练习题会显示标准答案反馈。")


def render_questionnaire():
    st.title("实验结束问卷")
    st.markdown("请根据你在实验中的真实感受作答，没有对错之分。")
    exp_type = st.session_state.get("participant_meta", {}).get("exp_type", "exp1")

    with st.form("questionnaire_form"):
        st.markdown("### 第一部分：对 AI 系统的整体评价")
        understanding = st.slider("1. 我能够理解 AI 给出该判断建议的依据。", 1, 7, 4)
        trust = st.slider("2. 我认为该 AI 系统的建议总体上值得信任。", 1, 7, 4)
        reliance = st.slider("3. 在做最终判断时，我在多大程度上参考了 AI 的建议？", 1, 7, 4)
        ai_helpfulness = st.slider("4. AI 的建议对我完成任务有帮助。", 1, 7, 4)

        st.markdown("### 第二部分：认知负荷评估（NASA-TLX）")
        nasa_mental = st.slider("5. 脑力需求：完成任务需要多少脑力投入？", 0, 100, 50)
        nasa_temporal = st.slider("6. 时间压力：你感受到多大的时间压力？", 0, 100, 50)
        nasa_effort = st.slider("7. 努力程度：你需要付出多少努力来完成任务？", 0, 100, 50)
        nasa_frustration = st.slider("8. 挫败感：你在任务中感到多少挫败、烦躁或压力？", 0, 100, 50)
        nasa_performance = st.slider("9. 你对自己在任务中表现的满意程度如何？", 0, 100, 50)

        st.markdown("### 第三部分：判断策略")
        if exp_type == "exp1":
            strategy = st.radio(
                "10. 在做最终判断时，你通常的策略是？",
                ["主要依靠自己的图像判断", "图像判断和AI建议各参考一半", "主要参考AI建议", "视情况而定"],
                index=3,
            )
            changed_reason = st.radio(
                "11. 当你改变了初步判断时，主要原因是？",
                ["AI建议与我不同，选择相信AI", "AI的解释让我重新审视图像", "不确定时偏向跟随AI", "我没有改变过判断"],
                index=3,
            )
            extra = {}
        else:
            strategy = st.radio(
                "10. 在做最终判断时，你通常更偏向哪种策略？",
                ["主要看质量，再兼顾成本", "质量与成本大致各占一半", "主要看成本，只要质量别太差", "视情况而定"],
                index=1,
            )
            changed_reason = st.radio(
                "11. 当你改变了初步判断时，主要原因是？",
                ["AI建议与我不同，选择相信AI", "看到质量信息后改变了判断", "看到价格后改变了判断", "我没有改变过判断"],
                index=3,
            )
            st.markdown("### 第四部分：多目标采购判断感受")
            quality_priority = st.slider("12. 在本实验中，你认为质量信息的重要性有多高？", 1, 7, 5)
            cost_priority = st.slider("13. 在本实验中，你认为价格信息的重要性有多高？", 1, 7, 4)
            rule_awareness = st.slider("14. 你是否感觉系统内部存在某种固定的采购判断规则？", 1, 7, 5)
            extra = {
                "quality_priority": quality_priority,
                "cost_priority": cost_priority,
                "rule_awareness": rule_awareness,
            }

        comments = st.text_area("15. 如有其他想说的（例如：哪些题目较难、对实验的建议等），请在此填写：", placeholder="选填")
        submitted = st.form_submit_button("提交问卷", type="primary", use_container_width=True)

    if submitted:
        st.session_state["questionnaire"] = {
            "understanding": understanding,
            "trust": trust,
            "reliance": reliance,
            "ai_helpfulness": ai_helpfulness,
            "nasa_mental": nasa_mental,
            "nasa_temporal": nasa_temporal,
            "nasa_effort": nasa_effort,
            "nasa_frustration": nasa_frustration,
            "nasa_performance": nasa_performance,
            "strategy": map_strategy_code(strategy),
            "changed_reason": map_changed_reason_code(changed_reason),
            "comments": safe_str(comments),
            **extra,
        }
        save_progress()
        st.session_state["stage"] = "finish"
        st.rerun()


def render_finish():
    st.title("🎉 实验完成")
    st.success("感谢你的参与，数据已自动保存。")
    participant_id = st.session_state["participant_meta"].get("participant_id", "unknown")
    out_dir = ensure_results_dir(participant_id)
    st.markdown("研究者可在以下位置找到保存文件：")
    st.code(str(out_dir / OUTPUT_XLSX_NAME), language="text")

    if st.button("🏠 下一位被试（返回首页）", use_container_width=True, type="primary"):
        reset_experiment()
        st.session_state["stage"] = "setup"
        st.rerun()


def render_sidebar():
    with st.sidebar:
        st.title("管理员设置")
        st.session_state["show_debug"] = st.checkbox("显示调试信息", value=False)
        st.write("默认题库会优先读取多目标采购版工作簿。")
        if st.session_state.get("exp_meta"):
            with st.expander("当前会话信息"):
                st.write(st.session_state.get("exp_meta", {}))
                st.write(st.session_state.get("participant_meta", {}))
        st.markdown("---")
        if st.button("重置当前会话", use_container_width=True):
            reset_experiment()
            st.rerun()


def validate_ready(exp1_df: pd.DataFrame, exp2_df: pd.DataFrame, practice_df: pd.DataFrame) -> bool:
    if exp1_df.empty or exp2_df.empty or practice_df.empty:
        st.warning("题库未成功加载完整，请先检查工作簿路径和 sheet 结构。")
        return False
    if not DATASET_ROOT.exists():
        st.warning(f"当前图片根目录不存在：{DATASET_ROOT}。如果图片不显示，请优先检查该路径。")
    return True


def main():
    init_session()
    render_sidebar()
    workbook_path, exp1_df, exp2_df, practice_df = load_all_banks()
    st.session_state["workbook_path"] = workbook_path
    stage = st.session_state["stage"]

    if stage == "setup":
        render_setup(exp1_df, exp2_df, practice_df)
        return

    if not validate_ready(exp1_df, exp2_df, practice_df):
        st.stop()

    if stage == "consent":
        render_consent()
    elif stage == "instruction":
        render_instruction()
    elif stage == "practice":
        render_trial(st.session_state["practice_trials"], "practice")
    elif stage == "formal":
        render_trial(st.session_state["trials"], "formal")
    elif stage == "rest":
        render_rest()
    elif stage == "questionnaire":
        render_questionnaire()
    elif stage == "finish":
        render_finish()


if __name__ == "__main__":
    main()
