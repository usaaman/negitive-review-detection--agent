"""
app.py
-------
Flask backend — UI serve karta hai aur agent_logic.py ke functions
ko call karta hai jab user "Run Scan" dabaye.
"""

from flask import Flask, render_template, request, jsonify, send_from_directory
import agent_logic
import traceback

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/scan", methods=["POST"])
def scan():
    data = request.get_json()

    location = data.get("location", "").strip()
    category = data.get("category", "").strip()
    max_businesses = int(data.get("max_businesses", 10))
    max_reviews = int(data.get("max_reviews", 10))
    rating_threshold = float(data.get("rating_threshold", 4.5))
    negative_star_max = int(data.get("negative_star_max", 3))

    if not location or not category:
        return jsonify({"error": "Location aur category dono zaroori hain."}), 400

    try:
        output = agent_logic.run_agent(
            location, category, max_businesses, max_reviews,
            rating_threshold, negative_star_max
        )
        return jsonify({
            "success": True,
            "results": output["results"],
            "filename": output["filename"],
            "total_scanned": output["total_scanned"],
            "flagged_count": output["flagged_count"],
            "dropped_no_contact": output["dropped_no_contact"],
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/download/<filename>")
def download(filename):
    return send_from_directory(agent_logic.OUTPUT_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
