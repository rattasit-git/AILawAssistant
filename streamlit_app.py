import streamlit as st
import json
import os
import re
import requests
import time
import concurrent.futures
import pypdf
import docx
from dotenv import load_dotenv
import google.generativeai as genai  # Google Gemini SDK

# Load environment variables
load_dotenv()
CHATGEN_API_KEY = os.getenv("CHATGEN_API_KEY")
CHATGEN_API_URL = "https://chatgen.scmc.cmu.ac.th/api/chat/completions"

st.set_page_config(layout="wide")

RUBRIC_DIR = "rubrics"
if not os.path.exists(RUBRIC_DIR):
    os.makedirs(RUBRIC_DIR)

def list_rubrics():
    return [f for f in os.listdir(RUBRIC_DIR) if f.endswith(".json")]

def load_criteria(rubric_filename):
    path = os.path.join(RUBRIC_DIR, rubric_filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            criteria = data.get("criteria", [])
            for c in criteria:
                c["weight"] = float(c.get("weight", 1.0))
            return criteria
    except Exception:
        return []

def save_criteria(criteria, rubric_filename):
    path = os.path.join(RUBRIC_DIR, rubric_filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"criteria": criteria}, f, ensure_ascii=False, indent=2)

def read_pdf(file):
    try:
        pdf_reader = pypdf.PdfReader(file)
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text if text else None
    except Exception as e:
        st.error(f"Error reading PDF: {e}")
        return None

def read_docx(file):
    try:
        doc = docx.Document(file)
        text = ""
        for p in doc.paragraphs:
            text += p.text + "\n"
        return text
    except Exception as e:
        st.error(f"Error reading DOCX: {e}")
        return None

def evaluate_with_chatgen(proposal_text, criterion):
    try:
        headers = {
            "Authorization": f"Bearer {CHATGEN_API_KEY}",
            "Content-Type": "application/json"
        }
        prompt = criterion['prompt']
        payload = {
            "model": "gpt-4.1",
            "messages": [
                {
                    "role": "system",
                    "content": "คุณคือผู้ประเมินข้อเสนอโครงการระดับสูงที่มีความเชี่ยวชาญและประสบการณ์อย่างกว้างขวาง..."
                },
                {
                    "role": "user",
                    "content": f"""ข้อเสนอโครงการวิจัย: {proposal_text}\n\nเกณฑ์การพิจารณา: {criterion['name']}\n{prompt}\nโปรดให้คะแนน (0-10) และข้อเสนอแนะใน 2-3 หรือหากเนื้อหาไม่เกี่ยวข้องให้แจ้งว่าไม่สามารถประเมินได้ โดยขึ้นต้นด้วย "คะแนน: X" ตามด้วยข้อเสนอแนะ"""
                }
            ],
            "temperature": 0.5,
            "max_tokens": 500
        }
        response = requests.post(CHATGEN_API_URL, json=payload, headers=headers, timeout=300)
        response.raise_for_status()
        result_content = response.json()["choices"][0]["message"]["content"]
        score_match = re.search(r'(?:คะแนน|Score):\s*(\d{1,2}(?:\.\d+)?)', result_content, re.IGNORECASE)
        raw_score = 0
        if score_match:
            try:
                raw_score = int(float(score_match.group(1)))
                if not (0 <= raw_score <= 10):
                    raw_score = 0
            except ValueError:
                raw_score = 0
        else:
            fallback_match = re.search(r'\b(\d{1,2})\b', result_content)
            if fallback_match:
                try:
                    potential_score = int(fallback_match.group(1))
                    if 0 <= potential_score <= 10:
                        raw_score = potential_score
                except ValueError:
                    pass
        return result_content, raw_score
    except Exception as e:
        return f"API error: {str(e)}", 0

# Sidebar rubric selection and management

rubric_files = list_rubrics()
if "selected_rubric" not in st.session_state:
    st.session_state.selected_rubric = rubric_files[0] if rubric_files else ""

st.sidebar.title("Rubric Management")

if rubric_files:
    selected = st.sidebar.selectbox("Select rubric", rubric_files, index=rubric_files.index(st.session_state.selected_rubric) if st.session_state.selected_rubric in rubric_files else 0)
    st.session_state.selected_rubric = selected
else:
    st.sidebar.info("No rubrics found. Please create one.")

with st.sidebar.expander("➕ Create New Rubric", expanded=False):
    new_name = st.text_input("New rubric file name (without .json):", key="new_rubric_name")
    if st.button("Create Rubric"):
        if new_name:
            filename = new_name.strip() + ".json"
            if filename in rubric_files:
                st.error("Rubric already exists.")
            else:
                save_criteria([], filename)
                st.success(f"Created rubric {filename}")
                st.session_state.selected_rubric = filename
                st.rerun()

with st.sidebar.expander("📄 Duplicate Rubric", expanded=False):
    if rubric_files:
        to_dup = st.selectbox("Rubric to duplicate", rubric_files, key="dup_select")
        dup_name = st.text_input("New rubric file name (without .json):", key="dup_name")
        if st.button("Duplicate Rubric"):
            if dup_name:
                filename = dup_name.strip() + ".json"
                if filename in rubric_files:
                    st.error("Rubric already exists.")
                else:
                    with open(os.path.join(RUBRIC_DIR, to_dup), "r", encoding="utf-8") as f:
                        data = f.read()
                    with open(os.path.join(RUBRIC_DIR, filename), "w", encoding="utf-8") as f:
                        f.write(data)
                    st.success(f"Duplicated {to_dup} as {filename}")
                    st.session_state.selected_rubric = filename
                    st.rerun()
    else:
        st.info("No rubrics to duplicate.")

with st.sidebar.expander("🗑️ Delete Rubric", expanded=False):
    if rubric_files:
        to_del = st.selectbox("Rubric to delete", rubric_files, key="del_select")

        # Initialize checkbox state if not present
        if "confirm_delete" not in st.session_state:
            st.session_state.confirm_delete = False

        confirm = st.checkbox(f"Confirm to delete '{to_del}'", key="confirm_delete_checkbox",
                              value=st.session_state.confirm_delete)
        st.session_state.confirm_delete = confirm  # Keep checkbox state in session_state

        delete_btn = st.button("Delete Rubric")

        if delete_btn:
            if st.session_state.confirm_delete:
                os.remove(os.path.join(RUBRIC_DIR, to_del))
                st.success(f"Deleted {to_del}")
                # Reset checkbox state after deletion
                st.session_state.confirm_delete = False
                st.rerun()
            else:
                st.warning("Please confirm deletion by ticking the checkbox.")
    else:
        st.info("No rubrics to delete.")

# Page navigation

page = st.sidebar.radio("Go to", ["Evaluate Document", "Edit Rubric"])

def rubric_editor():
    # Display rubric name prominently
    rubric_name = st.session_state.selected_rubric if "selected_rubric" in st.session_state else "No Rubric Selected"
    st.markdown(f"<h2 style='font-weight:bold; color:#4B2E83; margin-bottom: 0.5rem;'>{rubric_name}</h2>", unsafe_allow_html=True)

    criteria = load_criteria(rubric_name)
    if criteria is None:
        criteria = []

    # (Optional) Show total weight as before
    total_weight = sum(float(c.get("weight", 1.0)) for c in criteria)
    st.info(f"**Total Weight:** {total_weight:.2f}")
    if abs(total_weight - 1.0) > 1e-6:
        st.warning("⚠️ Total weight is not 1.0. Consider adjusting your weights for balance.")

    with st.expander("➕ Add New Criterion", expanded=False):
        new_name = st.text_input("Criterion Name", key="new_crit_name")
        new_weight = st.number_input("Weight", min_value=0.0, value=1.0, step=0.05, key="new_crit_weight")
        new_prompt = st.text_area("Prompt (include all instructions here)", key="new_crit_prompt", height=500)  # FIX HEIGHT
        if st.button("Add Criterion"):
            if new_name and new_prompt:
                criteria.append({
                    "name": new_name,
                    "weight": float(new_weight),
                    "prompt": new_prompt
                })
                save_criteria(criteria, st.session_state.selected_rubric)
                st.success(f"Added criterion '{new_name}'")
                st.rerun()
            else:
                st.error("Please fill all fields")

    st.subheader("Edit Existing Criteria")
    for i, c in enumerate(criteria):
        with st.expander(f"{c['name']} (Weight: {c.get('weight',1.0):.2f})", expanded=False):
            name = st.text_input("Name", value=c["name"], key=f"name_{i}")
            weight = st.number_input("Weight", min_value=0.0, value=c.get("weight",1.0), step=0.05, key=f"weight_{i}")
            prompt = st.text_area("Prompt", value=c["prompt"], key=f"prompt_{i}", height=500)  # FIX HEIGHT
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Save", key=f"save_{i}"):
                    criteria[i] = {
                        "name": name,
                        "weight": float(weight),
                        "prompt": prompt
                    }
                    save_criteria(criteria, st.session_state.selected_rubric)
                    st.success(f"Saved criterion '{name}'")
                    st.rerun()
            with col2:
                if st.button("Delete", key=f"del_{i}"):
                    criteria.pop(i)
                    save_criteria(criteria, st.session_state.selected_rubric)
                    st.success(f"Deleted criterion '{name}'")
                    st.rerun()

    if criteria:
        st.download_button(
            "⬇️ Download Rubric JSON",
            json.dumps({"criteria": criteria}, indent=2, ensure_ascii=False),
            file_name=st.session_state.selected_rubric,
            mime="application/json"
        )

def proposal_evaluation():
    st.title("📝 Document Evaluation (Weighted Rubric)")

    criteria_list = load_criteria(st.session_state.selected_rubric)
    if not criteria_list:
        st.warning("No criteria found. Please add criteria in the editor.")
        return

    uploaded_file = st.file_uploader("Upload proposal file (PDF/DOCX)", type=["pdf", "docx"])
    proposal_text = ""
    if uploaded_file:
        if uploaded_file.type == "application/pdf":
            proposal_text = read_pdf(uploaded_file)
        else:
            proposal_text = read_docx(uploaded_file)
        if proposal_text:
            st.success("File loaded successfully.")
        else:
            st.error("Could not read file.")
    proposal_text = st.text_area("Or paste proposal text here:", value=proposal_text, height=300)

    # Red Evaluate button styling
    st.markdown(
        """
        <style>
        div.stButton > button:first-child {
            background-color: #d9534f;
            color: white;
            font-weight: bold;
            border-radius: 6px;
            border: 2px solid #b52b27;
            height: 3em;
            width: 100%;
            font-size: 1.2em;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    evaluate_clicked = st.button("Evaluate Proposal")

    # Initialize checklist status
    if "checklist_status" not in st.session_state or st.session_state.get("reset_checklist", False):
        st.session_state.checklist_status = [False] * len(criteria_list)
        st.session_state.reset_checklist = False

    # Persistent sidebar placeholder for checklist
    if "sidebar_checklist_placeholder" not in st.session_state:
        st.session_state.sidebar_checklist_placeholder = st.sidebar.empty()

    def update_sidebar_checklist():
        criteria_list = load_criteria(st.session_state.selected_rubric)
        lines = []
        for idx, crit in enumerate(criteria_list):
            # Ensure checklist_status has enough entries
            if idx < len(st.session_state.checklist_status):
                status = "✅" if st.session_state.checklist_status[idx] else "⏳"
            else:
                status = "⏳"  # Default to pending if index is out of bounds
            lines.append(f"- {status} {crit['name']}")
        checklist_md = "### ✅ Evaluation Progress\n" + "\n".join(lines)
        st.session_state.sidebar_checklist_placeholder.markdown(checklist_md)

    update_sidebar_checklist()

    if evaluate_clicked:
        if not proposal_text.strip():
            st.error("Please provide proposal text.")
            return

        st.session_state.checklist_status = [False] * len(criteria_list)
        update_sidebar_checklist()

        st.info("Evaluating... (parallel for all criteria)")

        progress_slots = [st.empty() for _ in criteria_list]
        status_slots = [st.empty() for _ in criteria_list]
        results = [None] * len(criteria_list)
        start_time = time.time()

        def evaluate_and_return(idx, criterion):
            feedback, score = evaluate_with_chatgen(proposal_text, criterion)
            return {
                "criterion": criterion["name"],
                "score": score,
                "weight": criterion.get("weight", 1.0),
                "weighted_score": score * criterion.get("weight", 1.0),
                "feedback": feedback,
                "idx": idx,
            }

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [executor.submit(evaluate_and_return, idx, criterion) for idx, criterion in enumerate(criteria_list)]
            completed = [False] * len(criteria_list)
            while not all(completed):
                for i, future in enumerate(futures):
                    if future.done() and not completed[i]:
                        res = future.result()
                        results[i] = res
                        progress_slots[i].progress(100, text=f"Done: {criteria_list[i]['name']}")
                        status_slots[i].success("Done")
                        completed[i] = True
                        st.session_state.checklist_status[i] = True
                        update_sidebar_checklist()
                    elif not completed[i]:
                        progress_slots[i].progress(50, text=f"Evaluating: {criteria_list[i]['name']}")
                        status_slots[i].info("Evaluating...")
                time.sleep(0.1)

        elapsed = time.time() - start_time
        st.success(f"Evaluation complete in {elapsed:.1f} seconds")

        total_weight = sum(c.get("weight", 1.0) for c in criteria_list)
        weighted_total = sum(r["weighted_score"] for r in results if r)
        st.markdown(f"**Total Weighted Score:** {weighted_total:.2f} / {10*total_weight:.2f}")

        st.write("### Results")
        st.table([{k: v for k, v in r.items() if k != "feedback" and k != "idx"} for r in results if r])
        for r in results:
            st.markdown(f"**{r['criterion']}**: {r['feedback']}")

        st.session_state.reset_checklist = True

if page == "Edit Rubric":
    rubric_editor()
else:
    proposal_evaluation()
