import hashlib
import json
import os
import random
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from PIL import Image
import streamlit as st

st.set_page_config(
    page_title="MVTec AD 解释透明度实验",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="collapsed",
)

APP_TITLE = "MVTec AD 解释透明度实验平台"
WORKBOOK_PATH = "05_metadata/MVTec_实验题库_完整版_解释优化版.xlsx"
DATASET_ROOT = "00_raw"
RESULTS_DIR_DEFAULT = "results"
PRACTICE_TRIALS = 4
BREAK_AFTER = 24

CONSENT_TEXT = """
**知情同意书**

本实验为本科毕业论文研究项目，研究主题为"AI 解释透明度对人机协作决策的影响"。

**实验内容：** 你将完成一系列工业产品质检判断任务，并在实验前后填写相关问卷。

**数据使用：** 实验过程中记录的所有数据（作答结果、反应时间、问卷评分）仅用于学术研究分析，不会涉及个人隐私信息的泄露。

**自愿参与：** 你可以在任何时候选择退出实验，不会有任何不良后果。

**实验时长：** 约 20–30 分钟。

请确认你已充分理解以上内容，并自愿参与本实验。
"""

# 产品缺陷说明
PRODUCT_STANDARDS = {
    "bottle": {
        "name": "瓶子（Bottle）",
        "ok": "瓶身表面完整光滑，无可见污渍、破损或异物附着。",
        "ng_types": [
            "污染（Contamination）：瓶身表面有污渍、附着物或颜色异常区域",
            "大破损（Broken Large）：瓶口、瓶身出现较大缺口或破裂",
            "小破损（Broken Small）：瓶身出现细微裂缝或小缺口",
        ]
    },
    "capsule": {
        "name": "胶囊（Capsule）",
        "ok": "胶囊外壳完整，颜色均匀，无变形、裂缝或内容物渗漏。",
        "ng_types": [
            "裂缝（Crack）：胶囊壳体出现裂纹或断裂",
            "渗漏（Squeeze）：胶囊受挤压变形或内容物外漏",
            "压痕（Poke）：胶囊表面有明显凹陷或戳痕",
            "划痕（Scratch）：胶囊表面有线状划伤痕迹",
        ]
    },
    "metal_nut": {
        "name": "金属螺母（Metal Nut）",
        "ok": "螺母形状规则，颜色均匀，螺纹完整，无弯曲、翻转或划痕。",
        "ng_types": [
            "弯曲（Bent）：螺母出现变形或弯曲",
            "颜色异常（Color）：螺母表面颜色不均匀或有锈斑",
            "翻转（Flip）：螺母放置方向错误或翻面",
            "划痕（Scratch）：螺母表面有明显划伤",
        ]
    }
}


# ── 工具函数 ──────────────────────────────────────────────

def stable_hash_int(text: str) -> int:
    return int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)


def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    for c in df.columns:
        df[c] = df[c].apply(lambda x: "" if pd.isna(x) else str(x).strip())
    return df


def read_bank() -> pd.DataFrame:
    try:
        return normalize_df(pd.read_excel(WORKBOOK_PATH, sheet_name="题库总表"))
    except Exception as e:
        st.error(f"题库读取失败：{e}")
        return pd.DataFrame()


def parse_ai_correct(v: str) -> bool:
    return str(v).startswith("正确")


def calc_adoption(decision: str, ai_suggestion: str) -> str:
    return "采纳" if decision == ai_suggestion else "未采纳"


def calc_dependence(decision: str, ai_suggestion: str, ai_correct: str) -> str:
    adopted = decision == ai_suggestion
    if parse_ai_correct(ai_correct):
        return "适当依赖" if adopted else "依赖不足"
    return "过度依赖" if adopted else "适当依赖"


def resolve_image_path(raw_path: str) -> Path:
    if not raw_path:
        raise FileNotFoundError("题库中未提供图片路径。")

    raw_norm = str(raw_path).replace("\\", "/")
    root = Path(DATASET_ROOT)

    # 策略1：直接路径（本地调试用）
    direct = Path(raw_path)
    if direct.exists():
        return direct

    # 策略2：从 00_raw/ 截取相对路径
    if "00_raw/" in raw_norm:
        rel = raw_norm.split("00_raw/", 1)[1]
        candidate = root / Path(rel)
        if candidate.exists():
            return candidate

    # 策略3：从产品类别名截取
    parts = raw_norm.split("/")
    for key in ["bottle", "capsule", "metal_nut"]:
        if key in parts:
            idx = parts.index(key)
            rel = Path(*parts[idx:])
            candidate = root / rel
            if candidate.exists():
                return candidate

    raise FileNotFoundError(
        f"图片未找到：{raw_path}\n"
        f"请确认 00_raw/ 下包含对应子文件夹（含 good/ 文件夹）。"
    )


def ensure_results_dir(participant_id: str) -> Path:
    out_dir = Path(RESULTS_DIR_DEFAULT) / participant_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def save_json(path: Path, payload: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def save_csv(path: Path, rows: list):
    if rows:
        pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def get_condition_from_participant(participant_id: str, options: list) -> str:
    return options[stable_hash_int(participant_id) % len(options)]


# ── 题目构建 ──────────────────────────────────────────────

def build_exp1_trials(df: pd.DataFrame, participant_id: str, manual_condition=None):
    condition = manual_condition or get_condition_from_participant(participant_id, ["无解释", "有解释"])
    trials = []
    for _, row in df.iterrows():
        explanation_text = row["实验一-无解释呈现"] if condition == "无解释" else row["实验一-统一解释内容"]
        trials.append({
            "trial_id": row["题号"],
            "item_id": row["图片ID"],
            "category": row["产品类别"],
            "defect_type": row["缺陷类型"],
            "complexity": row["复杂度"],
            "true_label": row["真实标签"],
            "ai_suggestion": row["AI建议"],
            "ai_correct": row["AI是否正确"],
            "image_path": row["图片源路径"],
            "explanation_mode": condition,
            "explanation_text": explanation_text,
            "exp_name": "实验一",
        })
    rnd = random.Random(stable_hash_int(participant_id + "_exp1_order"))
    rnd.shuffle(trials)
    return trials, {"exp_name": "实验一", "condition": condition, "design": "组间"}


def build_exp2_trials(df: pd.DataFrame, participant_id: str):
    version = "A" if stable_hash_int(participant_id) % 2 == 0 else "B"
    tmp = df.copy()
    tmp["group_key"] = tmp["产品类别"] + "|" + tmp["复杂度"] + "|" + tmp["真实标签"]
    trials = []
    for _, g in tmp.groupby("group_key", sort=True):
        g = g.sort_values("题号").reset_index(drop=True)
        split = len(g) // 2
        metric_idx = set(g.index[:split]) if version == "A" else set(g.index[split:])
        for idx, row in g.iterrows():
            is_metric = idx in metric_idx
            trials.append({
                "trial_id": row["题号"],
                "item_id": row["图片ID"],
                "category": row["产品类别"],
                "defect_type": row["缺陷类型"],
                "complexity": row["复杂度"],
                "true_label": row["真实标签"],
                "ai_suggestion": row["AI建议"],
                "ai_correct": row["AI是否正确"],
                "image_path": row["图片源路径"],
                "explanation_mode": "指标型解释" if is_metric else "理由型解释",
                "explanation_text": row["实验二-指标型解释内容"] if is_metric else row["实验二-理由型解释内容"],
                "exp_name": "实验二",
            })
    rnd = random.Random(stable_hash_int(participant_id + "_exp2_order"))
    rnd.shuffle(trials)
    return trials, {"exp_name": "实验二", "counterbalance_version": version, "design": "被试内"}


def select_practice_trials(trials: list, participant_id: str, n: int):
    if n <= 0:
        return []
    rnd = random.Random(stable_hash_int(participant_id + "_practice"))
    copied = [t.copy() for t in trials]
    rnd.shuffle(copied)
    practice = copied[:min(n, len(copied))]
    for t in practice:
        t["is_practice"] = True
    return practice


# ── Session 管理 ──────────────────────────────────────────

def init_session():
    defaults = {
        "stage": "setup",
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
        "finished": False,
        "rest_done": False,
        "trial_phase": "initial",
        "initial_decision": None,
        "initial_rt_ms": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def reset_experiment():
    keys = [
        "stage", "participant_meta", "exp_meta", "trials", "practice_trials",
        "current_index", "current_render_id", "trial_start_ts", "exp_start_ts",
        "responses", "questionnaire", "finished", "rest_done",
        "trial_phase", "initial_decision", "initial_rt_ms",
    ]
    for k in keys:
        if k in st.session_state:
            del st.session_state[k]
    init_session()


def save_progress():
    participant_id = st.session_state["participant_meta"].get("participant_id", "unknown")
    out_dir = ensure_results_dir(participant_id)
    save_json(out_dir / "session_meta.json", {
        "participant_meta": st.session_state["participant_meta"],
        "exp_meta": st.session_state["exp_meta"],
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    })
    save_csv(out_dir / "trial_responses.csv", st.session_state["responses"])
    if st.session_state.get("questionnaire"):
        save_json(out_dir / "questionnaire.json", st.session_state["questionnaire"])


# ── 页面渲染 ──────────────────────────────────────────────

def render_setup(df: pd.DataFrame):
    st.title(APP_TITLE)

    st.info(
        "**参与须知：** 本实验分为实验一和实验二两种类型，**每位被试只需完成其中一种**。"
        "请根据研究者的安排选择你的实验类型，并如实填写以下基本信息。"
    )

    with st.form("setup_form"):
        st.markdown("#### 被试基本信息")
        c1, c2, c3 = st.columns(3)
        with c1:
            participant_id = st.text_input("被试编号 *", placeholder="例如：P001")
            name = st.text_input("姓名 *", placeholder="请输入真实姓名")
        with c2:
            student_id = st.text_input("学号 *", placeholder="请输入学号")
            age = st.text_input("年龄 *", placeholder="例如：21")
        with c3:
            gender = st.selectbox("性别 *", ["", "女", "男"])
            major = st.text_input("专业 *", placeholder="例如：工业工程")

        st.markdown("#### 实验类型")
        exp_name = st.selectbox(
            "实验类型 *（请按研究者指示选择）",
            ["实验一：有无解释", "实验二：解释形式"]
        )

        submitted = st.form_submit_button("确认并进入实验", use_container_width=True, type="primary")

    if submitted:
        errors = []
        if not participant_id.strip(): errors.append("被试编号")
        if not name.strip(): errors.append("姓名")
        if not student_id.strip(): errors.append("学号")
        if not age.strip(): errors.append("年龄")
        if not gender: errors.append("性别")
        if not major.strip(): errors.append("专业")
        if errors:
            st.error(f"请填写以下必填项：{'、'.join(errors)}")
            return
        if df.empty:
            st.error("题库加载失败，请联系研究者。")
            return

        pid = participant_id.strip()
        # 条件自动分配，对被试不可见
        if exp_name.startswith("实验一"):
            condition = get_condition_from_participant(pid, ["无解释", "有解释"])
            trials, meta = build_exp1_trials(df, pid, condition)
        else:
            trials, meta = build_exp2_trials(df, pid)

        st.session_state["participant_meta"] = {
            "participant_id": pid,
            "name": name.strip(),
            "student_id": student_id.strip(),
            "age": age.strip(),
            "gender": gender,
            "major": major.strip(),
            "exp_type": exp_name,
            "exp_condition": meta.get("condition", meta.get("counterbalance_version", "")),
        }
        st.session_state["exp_meta"] = meta
        st.session_state["trials"] = trials
        st.session_state["practice_trials"] = select_practice_trials(trials, pid, PRACTICE_TRIALS)
        st.session_state["current_index"] = 0
        st.session_state["responses"] = []
        st.session_state["stage"] = "consent"
        st.rerun()

    with st.expander("查看题库摘要（研究者用）", expanded=False):
        if not df.empty:
            st.dataframe(
                df.groupby(["产品类别", "复杂度", "真实标签"]).size().reset_index(name="数量"),
                hide_index=True, use_container_width=True
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
    st.title("实验说明")

    st.markdown("---")
    st.markdown("### 一、实验任务")
    st.markdown("""
你将看到一系列工业产品图像，每张图片展示的是 **瓶子、胶囊或金属螺母** 之一。
你的任务是判断图中产品是否合格：

| 判定 | 含义 |
|------|------|
| ✅ **OK（合格）** | 产品外观无明显缺陷，可以出厂 |
| ❌ **NG（不合格）** | 产品存在可见异常，不可出厂 |
    """)

    st.markdown("---")
    st.markdown("### 二、各产品合格/不合格标准")

    for key, info in PRODUCT_STANDARDS.items():
        with st.expander(f"📦 {info['name']}", expanded=True):
            st.markdown(f"**✅ 合格品：** {info['ok']}")
            st.markdown("**❌ 不合格品常见缺陷：**")
            for d in info["ng_types"]:
                st.markdown(f"- {d}")

    st.markdown("---")
    st.markdown("### 三、每道题的作答流程")
    st.markdown("""
每道题分为 **两个步骤**：

**第一步 — 独立判断（看不到 AI 建议）**
> 请先仔细观察产品图像，根据自己的判断选择 OK 或 NG。

**第二步 — 参考 AI 后最终决策**
> 完成初步判断后，系统会显示 AI 的检测结果（部分题目还会附上解释信息）。
> 请综合图像与 AI 建议，给出你的最终判断。最终判断可与初步判断相同或不同。
    """)

    st.markdown("---")
    st.markdown("""
**⚠️ 注意事项**
- 正式实验共 **48 题**，中途会有一次短暂休息（第 24 题后）。
- 前 4 题为练习题，不计入正式数据。
- 两步判断都会记录反应时间，请尽量**认真且不要过度拖延**。
- 实验结束后请完成简短问卷。
    """)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("返回知情同意", use_container_width=True):
            st.session_state["stage"] = "consent"
            st.rerun()
    with c2:
        label = "进入练习题" if PRACTICE_TRIALS > 0 else "开始正式实验"
        if st.button(label, type="primary", use_container_width=True):
            st.session_state["stage"] = "practice" if PRACTICE_TRIALS > 0 else "formal"
            st.session_state["current_index"] = 0
            st.session_state["current_render_id"] = None
            st.rerun()


def render_rest():
    st.title("请稍作休息 ☕")
    st.markdown("你已完成前 24 题，已经完成一半了！建议休息 1–2 分钟后再继续。")
    elapsed = int(time.time() - (st.session_state.get("exp_start_ts") or time.time()))
    st.info(f"当前已用时：{elapsed // 60} 分 {elapsed % 60} 秒")
    if st.button("我已休息好，继续实验", type="primary", use_container_width=True):
        st.session_state["rest_done"] = True
        st.session_state["stage"] = "formal"
        st.session_state["current_render_id"] = None
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

    trial = trials[idx]
    render_uid = f"{mode}_{trial['trial_id']}_{idx}"

    # 新题初始化
    if st.session_state["current_render_id"] != render_uid:
        st.session_state["current_render_id"] = render_uid
        st.session_state["trial_start_ts"] = time.time()
        st.session_state["trial_phase"] = "initial"
        st.session_state["initial_decision"] = None
        st.session_state["initial_rt_ms"] = None

    # 休息检查
    if mode == "formal" and idx == BREAK_AFTER and not st.session_state.get("rest_done", False):
        st.session_state["stage"] = "rest"
        st.rerun()

    # 实验开始时间
    if mode == "formal" and not st.session_state.get("exp_start_ts"):
        st.session_state["exp_start_ts"] = time.time()

    # ── 顶部进度区域 ──
    if mode == "formal":
        elapsed = int(time.time() - st.session_state["exp_start_ts"])
        em, es = elapsed // 60, elapsed % 60
        st.markdown(
            f"<div style='text-align:center;padding:6px 0;font-size:0.95rem;'>"
            f"⏱️ 已用时 <b>{em:02d}:{es:02d}</b> &nbsp;|&nbsp; 进度 <b>{idx} / {total}</b> 题</div>",
            unsafe_allow_html=True
        )
        st.progress(idx / total)
    else:
        st.progress(idx / total, text=f"练习题进度：{idx}/{total}")

    st.subheader(f"{'练习题' if mode == 'practice' else '正式题'} {idx + 1} / {total}")

    phase = st.session_state.get("trial_phase", "initial")
    c1, c2 = st.columns([1.2, 1.0])

    with c1:
        try:
            img_path = resolve_image_path(trial["image_path"])
            st.image(Image.open(img_path), use_container_width=True)
        except Exception as e:
            st.error(f"图片读取失败：{e}")

    with c2:
        if phase == "initial":
            # ── 第一步：独立判断 ──
            st.markdown("### 第一步：请先独立判断")
            st.info("仔细观察图像，在看到 AI 建议之前，先给出你的初步判断。")
            st.markdown("---")
            st.markdown("**你的初步判断：**")
            col_ok, col_ng = st.columns(2)

            def submit_initial(decision: str):
                rt = int((time.time() - st.session_state["trial_start_ts"]) * 1000)
                st.session_state["initial_decision"] = decision
                st.session_state["initial_rt_ms"] = rt
                st.session_state["trial_phase"] = "final"
                st.session_state["trial_start_ts"] = time.time()
                st.rerun()

            with col_ok:
                if st.button("✅ OK（合格）", key=f"i_ok_{render_uid}", use_container_width=True):
                    submit_initial("OK（合格）")
            with col_ng:
                if st.button("❌ NG（不合格）", key=f"i_ng_{render_uid}", use_container_width=True):
                    submit_initial("NG（不合格）")

            st.caption("完成初步判断后，将显示 AI 建议，再进行最终决策。" if mode != "practice" else "练习题不计入正式数据。")

        else:
            # ── 第二步：参考AI后最终决策 ──
            st.markdown("### 第二步：参考 AI 建议，做最终判断")
            st.info(f"**AI 判定：{trial['ai_suggestion']}**")

            if trial["explanation_mode"] not in ("无解释", ""):
                st.write(trial["explanation_text"])

            st.caption(f"你的初步判断：**{st.session_state['initial_decision']}**")
            st.markdown("---")
            st.markdown("**你的最终判断（可与初步判断相同或不同）：**")
            col_ok, col_ng = st.columns(2)

            def submit_final(decision: str):
                rt = int((time.time() - st.session_state["trial_start_ts"]) * 1000)
                init_dec = st.session_state["initial_decision"]
                record = {
                    # 被试信息
                    "participant_id": st.session_state["participant_meta"].get("participant_id", ""),
                    "name": st.session_state["participant_meta"].get("name", ""),
                    "student_id": st.session_state["participant_meta"].get("student_id", ""),
                    "age": st.session_state["participant_meta"].get("age", ""),
                    "gender": st.session_state["participant_meta"].get("gender", ""),
                    "major": st.session_state["participant_meta"].get("major", ""),
                    # 实验信息
                    "exp_name": trial["exp_name"],
                    "exp_condition": st.session_state["participant_meta"].get("exp_condition", ""),
                    "trial_stage": mode,
                    "trial_index": idx + 1,
                    # 题目信息
                    "trial_id": trial["trial_id"],
                    "item_id": trial["item_id"],
                    "category": trial["category"],
                    "defect_type": trial["defect_type"],
                    "complexity": trial["complexity"],
                    "true_label": trial["true_label"],
                    "ai_suggestion": trial["ai_suggestion"],
                    "ai_correct": trial["ai_correct"],
                    "explanation_mode": trial["explanation_mode"],
                    # 作答数据
                    "initial_decision": init_dec,
                    "initial_rt_ms": st.session_state["initial_rt_ms"],
                    "final_decision": decision,
                    "final_rt_ms": rt,
                    "total_trial_rt_ms": (st.session_state["initial_rt_ms"] or 0) + rt,
                    "decision_changed": "是" if decision != init_dec else "否",
                    "initial_correct": "正确" if init_dec == trial["true_label"] else "错误",
                    "final_correct": "正确" if decision == trial["true_label"] else "错误",
                    "adoption": calc_adoption(decision, trial["ai_suggestion"]),
                    "dependence_type": calc_dependence(decision, trial["ai_suggestion"], trial["ai_correct"]),
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                }
                if mode != "practice":
                    st.session_state["responses"].append(record)
                    save_progress()
                st.session_state["current_index"] += 1
                st.session_state["current_render_id"] = None
                st.session_state["trial_phase"] = "initial"
                st.rerun()

            with col_ok:
                if st.button("✅ OK（合格）", key=f"f_ok_{render_uid}", use_container_width=True):
                    submit_final("OK（合格）")
            with col_ng:
                if st.button("❌ NG（不合格）", key=f"f_ng_{render_uid}", use_container_width=True):
                    submit_final("NG（不合格）")

            st.caption("练习题不计入正式数据。" if mode == "practice" else "点击后自动进入下一题。")


def render_questionnaire():
    st.title("实验结束问卷")
    st.markdown("请根据你在实验中的真实感受作答，没有对错之分。")
    exp_name = st.session_state["exp_meta"].get("exp_name", "")

    with st.form("questionnaire_form"):
        st.markdown("### 第一部分：对 AI 系统的整体评价")
        understanding = st.slider(
            "1. 我能够理解 AI 给出该判断的依据。",
            1, 7, 4,
            help="1=完全不理解，7=完全理解"
        )
        trust = st.slider(
            "2. 我认为该 AI 系统的判断总体上值得信任。",
            1, 7, 4,
            help="1=完全不信任，7=完全信任"
        )
        reliance = st.slider(
            "3. 在做最终判断时，我在多大程度上参考了 AI 的建议？",
            1, 7, 4,
            help="1=完全没有参考，7=完全依照AI建议"
        )
        ai_helpfulness = st.slider(
            "4. AI 的建议对我完成判断任务有帮助。",
            1, 7, 4,
            help="1=完全没帮助，7=非常有帮助"
        )

        st.markdown("### 第二部分：认知负荷评估（NASA-TLX）")
        nasa_mental = st.slider("5. 脑力需求：完成任务需要多少脑力投入？", 0, 100, 50, help="0=非常低，100=非常高")
        nasa_temporal = st.slider("6. 时间压力：你感受到多大的时间压力？", 0, 100, 50, help="0=非常低，100=非常高")
        nasa_effort = st.slider("7. 努力程度：你需要付出多少努力来完成任务？", 0, 100, 50, help="0=非常低，100=非常高")
        nasa_frustration = st.slider("8. 挫败感：你在任务中感到多少挫败、烦躁或压力？", 0, 100, 50, help="0=非常低，100=非常高")
        nasa_performance = st.slider("9. 你对自己在任务中表现的满意程度如何？", 0, 100, 50, help="0=非常不满意，100=非常满意")

        st.markdown("### 第三部分：判断策略")
        strategy = st.radio(
            "10. 在做最终判断时，你通常的策略是？",
            ["主要依靠自己的图像判断", "图像判断和AI建议各参考一半", "主要参考AI建议", "视情况而定"],
            index=3
        )
        changed_reason = st.radio(
            "11. 当你改变了初步判断时，主要原因是？",
            ["AI建议与我不同，选择相信AI", "AI的解释让我重新审视图像", "不确定时偏向跟随AI", "我没有改变过判断"],
            index=3
        )

        extra = {}
        if exp_name == "实验二":
            st.markdown("### 第四部分：解释形式对比（实验二专属）")
            easier = st.radio(
                "12. 你觉得哪种解释形式更容易理解？",
                ["指标型解释（数字/百分比）", "理由型解释（文字描述）", "两者差不多"]
            )
            more_trust = st.radio(
                "13. 你觉得哪种解释形式更让你信任AI的判断？",
                ["指标型解释（数字/百分比）", "理由型解释（文字描述）", "两者差不多"]
            )
            more_helpful = st.radio(
                "14. 你觉得哪种解释形式对你的最终判断帮助更大？",
                ["指标型解释（数字/百分比）", "理由型解释（文字描述）", "两者差不多"]
            )
            extra = {
                "easier_to_understand": easier,
                "more_trustworthy": more_trust,
                "more_helpful": more_helpful,
            }

        st.markdown("### 补充意见")
        comments = st.text_area(
            "15. 如有其他想说的（例如：哪些题目较难、对实验的建议等），请在此填写：",
            placeholder="选填"
        )

        submitted = st.form_submit_button("提交问卷", type="primary", use_container_width=True)

    if submitted:
        st.session_state["questionnaire"] = {
            "participant_id": st.session_state["participant_meta"].get("participant_id", ""),
            "understanding": understanding,
            "trust": trust,
            "reliance": reliance,
            "ai_helpfulness": ai_helpfulness,
            "nasa_mental": nasa_mental,
            "nasa_temporal": nasa_temporal,
            "nasa_effort": nasa_effort,
            "nasa_frustration": nasa_frustration,
            "nasa_performance": nasa_performance,
            "strategy": strategy,
            "changed_reason": changed_reason,
            "comments": comments.strip(),
            **extra,
        }
        save_progress()
        st.session_state["stage"] = "finish"
        st.rerun()


def render_finish():
    st.title("🎉 实验完成")
    st.success("感谢你的参与！请下载数据文件并发送给研究者。")

    participant_id = st.session_state["participant_meta"].get("participant_id", "unknown")
    responses = pd.DataFrame(st.session_state["responses"])

    if not responses.empty:
        # 统计摘要
        st.markdown("### 本次实验数据摘要")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("完成题数", len(responses))
        with col2:
            init_acc = (responses["initial_correct"] == "正确").mean() * 100 if "initial_correct" in responses.columns else 0
            st.metric("初步判断准确率", f"{init_acc:.1f}%")
        with col3:
            final_acc = (responses["final_correct"] == "正确").mean() * 100 if "final_correct" in responses.columns else 0
            st.metric("最终判断准确率", f"{final_acc:.1f}%")
        with col4:
            changed = (responses["decision_changed"] == "是").mean() * 100 if "decision_changed" in responses.columns else 0
            st.metric("判断改变率", f"{changed:.1f}%")

        col5, col6, col7 = st.columns(3)
        with col5:
            adoption = (responses["adoption"] == "采纳").mean() * 100 if "adoption" in responses.columns else 0
            st.metric("AI采纳率", f"{adoption:.1f}%")
        with col6:
            init_rt = responses["initial_rt_ms"].mean() if "initial_rt_ms" in responses.columns else 0
            st.metric("初步判断平均反应时", f"{init_rt:.0f} ms")
        with col7:
            final_rt = responses["final_rt_ms"].mean() if "final_rt_ms" in responses.columns else 0
            st.metric("最终判断平均反应时", f"{final_rt:.0f} ms")

        st.markdown("---")
        st.markdown("### 请下载以下数据文件并发送给研究者")
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                "⬇️ 下载实验作答数据（CSV）",
                data=responses.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
                file_name=f"{participant_id}_trial_responses.csv",
                mime="text/csv",
                use_container_width=True,
                type="primary",
            )
        with col_dl2:
            q = st.session_state.get("questionnaire", {})
            if q:
                st.download_button(
                    "⬇️ 下载问卷数据（CSV）",
                    data=pd.DataFrame([q]).to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
                    file_name=f"{participant_id}_questionnaire.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

    st.markdown("---")
    if st.button("🏠 下一位被试（返回首页）", use_container_width=True, type="primary"):
        reset_experiment()
        st.session_state["stage"] = "setup"
        st.rerun()


def render_sidebar():
    with st.sidebar:
        st.title("管理员设置")
        st.session_state["show_debug"] = st.checkbox("显示调试信息", value=False)
        if st.session_state.get("exp_meta"):
            with st.expander("当前会话信息"):
                st.write(st.session_state.get("exp_meta", {}))
                st.write(st.session_state.get("participant_meta", {}))
        st.markdown("---")
        if st.button("重置当前会话", use_container_width=True):
            reset_experiment()
            st.rerun()


# ── 主函数 ───────────────────────────────────────────────

def main():
    init_session()
    render_sidebar()

    df = read_bank() if st.session_state["stage"] == "setup" else read_bank()
    stage = st.session_state["stage"]

    if stage == "setup":
        render_setup(df)
    elif stage == "consent":
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
