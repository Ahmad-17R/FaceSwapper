import os
import uuid
import requests
from PIL import Image
from flask import Flask, request, send_file, jsonify

app = Flask(__name__)

API_KEY = "7e8538e57dmshef265340e4bf000p140341jsn9216783a5995"
API_HOST = "cartoon-yourself.p.rapidapi.com"
API_URL = "https://cartoon-yourself.p.rapidapi.com/facebody/api/portrait-animation/portrait-animation"

CARTOON_STYLE = "hongkong"
UPLOAD_FOLDER = "uploads"
RESULT_FOLDER = "results"
MAX_RESOLUTION = (2000, 2000)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULT_FOLDER, exist_ok=True)

def resize_image(image_path):
    img = Image.open(image_path)
    if img.width > MAX_RESOLUTION[0] or img.height > MAX_RESOLUTION[1]:
        img.thumbnail(MAX_RESOLUTION)
        resized_path = os.path.join(UPLOAD_FOLDER, f"resized_{os.path.basename(image_path)}")
        img.save(resized_path)
        return resized_path
    return image_path

def cartoonify_image(image_path, style):
    image_path = resize_image(image_path)

    with open(image_path, "rb") as img_file:
        files = {"image": img_file}
        data = {"type": style}
        headers = {
            "x-rapidapi-key": API_KEY,
            "x-rapidapi-host": API_HOST,
        }

        response = requests.post(API_URL, headers=headers, files=files, data=data)

        if response.status_code == 200:
            resp_json = response.json()
            image_url = resp_json.get("data", {}).get("image_url")
            if image_url:
                download_response = requests.get(image_url)
                if download_response.status_code == 200:
                    output_path = os.path.join(RESULT_FOLDER, f"cartoon_{uuid.uuid4().hex}.png")
                    with open(output_path, "wb") as f:
                        f.write(download_response.content)
                    return output_path
                else:
                    raise Exception("Failed to download cartoon image.")
            else:
                raise Exception("No image URL found in response.")
        else:
            raise Exception(f"Cartoonify API error: {response.status_code}, {response.text}")

@app.route("/cartoonify", methods=["POST"])
def cartoonify_endpoint():
    if "image" not in request.files:
        return jsonify({"error": "No image file uploaded"}), 400

    image = request.files["image"]
    filename = f"{uuid.uuid4().hex}_{image.filename}"
    image_path = os.path.join(UPLOAD_FOLDER, filename)
    image.save(image_path)

    try:
        output_path = cartoonify_image(image_path, CARTOON_STYLE)
        return send_file(output_path, mimetype="image/png")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860)
