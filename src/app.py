from flask import Flask, request, jsonify, render_template
import uuid
from agents.primary.agent import primary_graph

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("chat.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("msg")
    thread_id = data.get("thread_id")
    if not thread_id:
        thread_id = str(uuid.uuid4())
    config = {
        "configurable": {
            "passenger_id": "8149 604011",  # Hardcoded passenger_id for demonstration
            "thread_id": thread_id,
        }
    }
    
    final_state = None
    events = primary_graph.stream(
        {"messages": ("user", user_message)}, config, stream_mode="values"
    )
    for event in events:
        final_state = event

    ai_message = None
    # Cố gắng lấy message AI cuối cùng có nội dung
    if final_state and "messages" in final_state and final_state["messages"]:
        for msg in reversed(final_state["messages"]):
            msg_type = getattr(msg, "type", "")
            msg_content = getattr(msg, "content", "")
            if msg_type in ("ai", "assistant") and msg_content:
                ai_message = msg_content
                break

    # Fallback: nếu vẫn chưa tìm được thì dùng phần tử cuối cùng
    if ai_message is None and final_state and "messages" in final_state and final_state["messages"]:
        last_msg = final_state["messages"][-1]
        ai_message = getattr(last_msg, "content", "")

    # Đảm bảo luôn có nội dung trả về
    if not ai_message:
        ai_message = "Sorry, I couldn't get a response from the agent."

    # Chuẩn hóa về string
    if isinstance(ai_message, list):
        ai_message = " ".join(str(part) for part in ai_message)
    else:
        ai_message = str(ai_message)

    return jsonify({"response": ai_message, "thread_id": thread_id})

if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True, port=5000)

