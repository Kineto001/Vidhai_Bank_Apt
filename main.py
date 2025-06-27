import os
import json
import random
import math
import time
from flask import Flask, request, jsonify, render_template
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__, template_folder='templates', static_folder='static')

# --- CONFIGURATION ---
SOURCE_MATERIAL_FOLDER = "source_material"
# Updated for Bank Exams
SUBJECT_MAPPING = {
    "Quantitative Aptitude": "quantitative_aptitude",
    "Quantitative Aptitude (Additional)": "quantitative_aptitude_additional",
    "Reasoning Ability": "reasoning_ability",
    "English Language": "english_language"
}

# --- GEMINI API SETUP ---
try:
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        raise ValueError("GEMINI_API_KEY not found in environment variables.")
    genai.configure(api_key=gemini_api_key)
    # Using a powerful and current model suitable for complex generation
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
except Exception as e:
    print(f"Error configuring Gemini API: {e}")
    model = None

# --- HELPER FUNCTIONS ---
def clean_gemini_json_response(response_text):
    """Cleans the Gemini response to extract a valid JSON string."""
    start_index = response_text.find('[')
    end_index = response_text.rfind(']')
    if start_index != -1 and end_index != -1:
        return response_text[start_index:end_index+1]
    # Fallback for responses that don't use markdown code blocks
    return response_text.strip().replace("```json", "").replace("```", "")

# --- PROMPT TEMPLATES (MODIFIED FOR BANK EXAMS) ---
PROMPT_TEMPLATE = """
You are an expert Bank Exam (IBPS, SBI PO/Clerk level) question creator. Your task is to generate {num_questions} high-quality, challenging multiple-choice questions (MCQs) in English for the topic: '{topic}'. For this exercise, create exactly 4 options for each question.

**Source Context (Use if provided, otherwise use your expert knowledge):**
\"\"\"
{context}
\"\"\"

**Crucial Instructions:**
1.  **Difficulty:** Questions must be of a competitive banking exam standard (prelims to mains level). Focus on questions that require analytical and logical skills, not just simple recall.
2.  **Question Variety (Based on Topic):**
    *   **For Quantitative Aptitude:** Generate a mix of word problems, data interpretation sets (if the topic is DI), simplification/approximation, number series, quadratic equations. For DI, the question should describe a chart/table and then ask 1-2 questions based on it.
    *   **For Reasoning Ability:** Generate a mix of puzzles (seating arrangements, floor puzzles), syllogisms, blood relations, direction sense, coding-decoding, and inequalities.
    *   **For English Language:** Generate questions on reading comprehension (provide a short paragraph and then questions), error spotting, cloze tests, and para jumbles.
3.  **Formatting:**
    *   Return the output as a single, valid JSON array of objects. **Do not include any text, notes, or markdown outside the final JSON array.**
    *   For questions that require special formatting (e.g., paragraphs, data tables), use newline characters (`\\n`) within the JSON string to ensure readability.
4.  **Quality Control:** All questions, options, and explanations must be factually correct, clear, and unambiguous, matching the pattern of modern bank exams.

**JSON Object Structure (4 Options):**
{{
  "question": "The full question text, including any necessary context like paragraphs or data sets.",
  "options": [ "Option A", "Option B", "Option C", "Option D" ],
  "correct_answer_index": <index of the correct option, 0-3>,
  "explanation": "A clear, step-by-step explanation for why the correct answer is right, including formulas or methods used."
}}

Generate exactly {num_questions} questions now.
"""

FALLBACK_PROMPT_TEMPLATE = """
You are an expert Bank Exam question creator. Your task is to generate {num_questions} standard multiple-choice questions (MCQs) in English for the topic: '{topic}'. Create exactly 4 options for each question.

**Source Context (Use if provided, otherwise use your expert knowledge):**
\"\"\"
{context}
\"\"\"

**Instructions:**
1.  **Standard:** Questions must be of a standard Bank Exam (prelims) level. They must be accurate and meaningful.
2.  **Focus:** Concentrate on core, fundamental concepts related to the topic. Simple MCQs are perfect.
3.  **Format:** Return the output as a single, valid JSON array of objects. **Do not include any text, notes, or markdown outside the final JSON array.**

**JSON Object Structure (4 Options):**
{{
  "question": "The full question text.",
  "options": [ "Option A", "Option B", "Option C", "Option D" ],
  "correct_answer_index": <index of the correct option, 0-3>,
  "explanation": "A clear, concise explanation for why the correct answer is right."
}}

Generate exactly {num_questions} questions now.
"""

def generate_questions_for_topic(prompt_details):
    """Generates and parses questions for a single topic, with a fallback prompt on retry."""
    num_questions = prompt_details['num_questions']
    topic = prompt_details['topic']
    context = prompt_details['context']

    if num_questions <= 0:
        return []

    for attempt in range(2):
        prompt_to_use = PROMPT_TEMPLATE if attempt == 0 else FALLBACK_PROMPT_TEMPLATE
        if attempt > 0:
             print(f"Warning: Attempt 1 failed. Retrying for topic '{topic}' with a simplified fallback prompt.")
        
        prompt = prompt_to_use.format(num_questions=num_questions, topic=topic, context=context)

        try:
            response = model.generate_content(prompt)
            cleaned_json_str = clean_gemini_json_response(response.text)
            questions = json.loads(cleaned_json_str)
            if isinstance(questions, list) and len(questions) > 0:
                print(f"Successfully generated {len(questions)} questions for '{topic}' on attempt {attempt+1}.")
                for q in questions:
                    q['topic'] = topic
                return questions
        except json.JSONDecodeError as e:
            print(f"JSONDecodeError on attempt {attempt+1} for '{topic}': {e}. Response was: {cleaned_json_str}")
        except Exception as e:
            print(f"An unexpected error occurred on attempt {attempt+1} for '{topic}': {e}")

        time.sleep(1.5)

    print(f"Error: All attempts failed for topic '{topic}'. Returning empty list.")
    return []

# --- API ENDPOINTS ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/get-structure', methods=['GET'])
def get_structure():
    """
    MODIFIED: This function now looks for .txt files directly inside the subject folders,
    bypassing the need for a 'unit' subfolder. It creates a dummy 'unit' called 'Topics'
    to maintain the data structure expected by the frontend.
    """
    structure = {}
    if not os.path.isdir(SOURCE_MATERIAL_FOLDER):
        return jsonify({"error": f"Base folder '{SOURCE_MATERIAL_FOLDER}' not found."}), 404
    
    for subject_key, subject_folder in SUBJECT_MAPPING.items():
        subject_path = os.path.join(SOURCE_MATERIAL_FOLDER, subject_folder)
        if os.path.isdir(subject_path):
            # Find all .txt files directly in the subject directory
            topics = [f.replace('.txt', '') for f in os.listdir(subject_path) if f.endswith('.txt') and os.path.isfile(os.path.join(subject_path, f))]
            if topics:
                # Assign the list of topics to a single, dummy unit key
                structure[subject_key] = {"Topics": sorted(topics)}
    
    return jsonify(structure)


@app.route('/api/generate-test', methods=['POST'])
def generate_test():
    if not model:
        return jsonify({"error": "Gemini API is not configured."}), 500
    data = request.json
    subject = data.get('subject')
    topic = data.get('topic')
    num_questions = int(data.get('num_questions', 10))
    test_type = data.get('test_type', 'topic-wise')

    context_text = "No specific context provided. Generate questions based on general knowledge of the topic."
    
    # Case-insensitive lookup for subject folder
    subject_folder = None
    canonical_subject = None
    if subject:
        for key, value in SUBJECT_MAPPING.items():
            if key.lower() == subject.lower():
                subject_folder = value
                canonical_subject = key
                break

    context_available = False
    if subject_folder and topic:
        try:
            file_path = os.path.join(SOURCE_MATERIAL_FOLDER, subject_folder, f"{topic}.txt")
            with open(file_path, 'r', encoding='utf-8') as f:
                context_text = f.read()
            context_available = True
        except Exception:
            print(f"Note: Could not read source file for {subject}/{topic}. Will generate from general knowledge.")

    all_questions = []
    
    # 70/30 split logic for Topic-wise tests
    if test_type == 'topic-wise' and context_available:
        num_from_context = math.ceil(num_questions * 0.7)
        num_from_general = num_questions - num_from_context

        print(f"Generating {num_from_context} questions from context and {num_from_general} from general knowledge for '{topic}'.")

        # 1. Generate questions WITH context
        all_questions.extend(generate_questions_for_topic({
            'num_questions': num_from_context, 'topic': topic, 'context': context_text
        }))

        # 2. Generate questions WITHOUT context
        all_questions.extend(generate_questions_for_topic({
            'num_questions': num_from_general, 'topic': topic, 
            'context': "No specific context provided. Generate questions based on general knowledge of the topic."
        }))

    # Standard logic for Mock tests or if context file is missing
    else:
        all_questions = generate_questions_for_topic({
            'num_questions': num_questions, 'topic': topic, 'context': context_text
        })
        
    random.shuffle(all_questions)

    if not all_questions:
        return jsonify({"error": f"The AI failed to generate questions for the topic '{topic}' after multiple attempts. Please try again."}), 500
    
    return jsonify(all_questions)


@app.route('/api/chat-support', methods=['POST'])
def chat_support():
    if not model:
        return jsonify({"error": "Gemini API is not configured."}), 500
    data = request.json
    user_query = data.get('user_query')
    question_text = data.get('question_text')
    topic = data.get('topic', 'General')

    if not user_query or not question_text:
        return jsonify({"error": "Missing user_query or question_text"}), 400

    aptitude_hint = ""
    if topic and any(keyword in topic.lower() for keyword in ['aptitude', 'quantitative', 'math', 'data interpretation']):
        aptitude_hint = """
        **Special Instruction for Quantitative Question:** This is a Math/DI question. Guide the student on the method, formula, or the first logical step. For example: "Remember the formula for compound interest," or "First, calculate the total number of items to find the average." Do not solve the problem for them.
        """

    try:
        prompt = f"""
        You are "VidhAI", a helpful AI tutor for Bank exams. A student is stuck on a question. Your goal is to provide a useful hint *without giving away the answer*.

        **Test Question:** "{question_text}"
        **Student's Request:** "{user_query}"
        **Topic:** "{topic}"

        **Your Task:**
        - Provide a short, clear hint.
        - If the student asks for the answer, gently refuse and provide a clue instead.
        - If the question is from English (e.g., error spotting), you can explain the grammatical rule it relates to.
        - If the question is a Reasoning puzzle, suggest a starting point, like "Try drawing a diagram for the seating arrangement."
        - Maintain a supportive and encouraging tone.
        {aptitude_hint}
        """
        response = model.generate_content(prompt)
        return jsonify({"reply": response.text})
    except Exception as e:
        return jsonify({"error": f"An error occurred while getting a hint: {e}"}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)