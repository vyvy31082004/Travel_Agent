# from flask import Flask, request, jsonify, render_template
# import uuid
# from agents.primary.agent import primary_graph

# app = Flask(__name__)

# @app.route("/")
# def index():
#     return render_template("chat.html")

# @app.route("/chat", methods=["POST"])
# def chat():
#     data = request.get_json()
#     user_message = data.get("msg")
#     thread_id = data.get("thread_id") or str(uuid.uuid4())
#     config = {"configurable": {"thread_id": thread_id}}
#     snapshot = primary_graph.get_state(config)
#     old_count = len(snapshot.values.get("messages", [])) if snapshot.values else 0
#     result = primary_graph.invoke({"messages": ("user", user_message)}, config)
#     new_messages = result["messages"][old_count:]
#     ai_responses = []
#     for msg in new_messages:
#         if msg.type in ("ai", "assistant") and msg.content:

#             if "Proceeding with the next requested task" not in msg.content:
#                 ai_responses.append(msg.content)
    
#     response = "\n\n".join(ai_responses) if ai_responses else "Sorry, I couldn't get a response."
#     return jsonify({"response": response, "thread_id": thread_id})

# if __name__ == "__main__":
#     app.run(host='0.0.0.0', debug=True, port=5000)

import asyncio
import uuid

from flask import Flask, jsonify, render_template, request

from agents.primary.agent import build_primary_graph

app = Flask(__name__)

# Khởi tạo graph một lần khi server start (MCP servers phải đang chạy trước)
primary_graph = asyncio.run(build_primary_graph())


@app.route("/")
def index():
    return render_template("chat.html")


@app.route("/chat", methods=["POST"])
async def chat():
    data = request.get_json()
    user_message = data.get("msg")
    thread_id = data.get("thread_id") or str(uuid.uuid4())
    config = {
        "configurable": {"thread_id": thread_id},
        "run_name": "customer_support_agent",
    }

    snapshot = primary_graph.get_state(config)
    old_count = len(snapshot.values.get("messages", [])) if snapshot.values else 0

    # ainvoke vì subgraph flight/hotel/excursion là async
    result = await primary_graph.ainvoke({"messages": ("user", user_message)}, config)

    new_messages = result["messages"][old_count:]
    ai_responses = []
    for msg in new_messages:
        if msg.type in ("ai", "assistant") and msg.content:
            if "Proceeding with the next requested task" not in msg.content:
                ai_responses.append(msg.content)

    response = "\n\n".join(ai_responses) if ai_responses else "Sorry, I couldn't get a response."
    return jsonify({"response": response, "thread_id": thread_id})


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5000)