import os
import json
import base64
from flask import Flask, request, jsonify
from google.generativeai import GenerativeModel
from google.generativeai.types import GenerationConfig, Part
import firebase_admin
from firebase_admin import credentials, firestore

# --- Configuration & Setup ---

# It's a good practice to store secrets like your API key in environment variables,
# but for this example, we'll use a placeholder.
# In a production environment, you would never hardcode this.
# You could set it using `export API_KEY='your-key-here'` in your server's shell.
API_KEY = os.environ.get("API_KEY", "")

# This is a placeholder for your Firebase service account key file.
# You will need to download this JSON file from your Firebase project settings
# and place it in your project's root directory on the server.
# In production, you would use a more secure method like Google Cloud's Secret Manager.
SERVICE_ACCOUNT_KEY_PATH = "path/to/your/service-account-key.json"

# --- Firebase Admin SDK Initialization ---
# The Admin SDK allows the backend to securely access Firestore.
try:
    if not firebase_admin._apps:
        # Load the service account credentials from the JSON file.
        cred = credentials.Certificate(SERVICE_ACCOUNT_KEY_PATH)
        # Initialize the Firebase app.
        firebase_admin.initialize_app(cred)
    
    # Get a reference to the Firestore database client.
    db = firestore.client()
    print("Firebase Admin SDK initialized successfully.")
except Exception as e:
    print(f"Error initializing Firebase Admin SDK: {e}")
    db = None

# --- Gemini API Configuration ---
# Use the Gemini API client. The API key is loaded from the environment.
# Note: You would need to `pip install -q -U google-generativeai` on your server.
model = GenerativeModel("gemini-1.5-pro")

# --- Flask Server Setup ---
app = Flask(__name__)

# The Flask application's main route
@app.route('/', methods=['GET'])
def home():
    """A simple home route to confirm the server is running."""
    return "The backend server is running!"

# The main API endpoint for parsing receipts
@app.route('/parse-receipt', methods=['POST'])
def parse_receipt():
    """
    Handles a POST request with a receipt image and sends it to the Gemini API
    for parsing.
    """
    # Check if a file was included in the request
    if 'image' not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    image_file = request.files['image']

    # Read the image data and encode it in base64
    try:
        image_bytes = image_file.read()
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
    except Exception as e:
        return jsonify({"error": f"Failed to read image file: {str(e)}"}), 500

    # --- Construct the prompt for Gemini ---
    prompt_text = (
        "You are a highly accurate receipt item parser. "
        "Take the provided image of a grocery receipt and extract a JSON array "
        "of objects. Each object in the array should have the following keys: "
        "'receiptName' (the raw item name from the receipt), "
        "'humanName' (a human-readable, common name for the item), "
        "'quantity' (the number of units), "
        "'cost' (the total cost for that item, as a float), "
        "'useByDate' (a reasonable estimated use by date in YYYY-MM-DD format), and "
        "'storage' (the most likely storage location: 'Fridge', 'Freezer', 'Cupboard', or 'Countertop')."
        "\n\nOnly return the JSON array. Do not include any other text."
    )

    # Combine the text prompt with the image data for a multimodal request.
    prompt_parts = [
        Part(text=prompt_text),
        Part(inline_data={'mime_type': 'image/jpeg', 'data': base64_image})
    ]

    # --- Call the Gemini API ---
    try:
        response = model.generate_content(prompt_parts)
        parsed_data = json.loads(response.text)
        return jsonify(parsed_data), 200
    except json.JSONDecodeError as e:
        print(f"JSON parsing error: {e}")
        print(f"Received text: {response.text}")
        return jsonify({"error": "Failed to parse data from Gemini. Invalid JSON response."}), 500
    except Exception as e:
        print(f"Error with Gemini API call: {e}")
        return jsonify({"error": "An unexpected error occurred with the Gemini API."}), 500

# The new API endpoint to save data to Firestore
@app.route('/save-items', methods=['POST'])
def save_items():
    """
    Receives an array of grocery items and saves them to the Firestore database.
    """
    if db is None:
        return jsonify({"error": "Database not initialized. Cannot save data."}), 500

    try:
        # Get the JSON data sent from the front-end.
        items_data = request.get_json()

        if not isinstance(items_data, list):
            return jsonify({"error": "Invalid data format. Expected a JSON array."}), 400

        # We need a user ID to save the data to the correct location in Firestore.
        # This user ID would typically come from an authentication system or a token.
        # For this prototype, we'll get it from a header sent by the front-end.
        user_id = request.headers.get('X-User-ID')
        if not user_id:
            return jsonify({"error": "User ID not provided in request headers."}), 400

        # Create a reference to the Firestore collection for this user's data.
        # This matches the path specified in the front-end code.
        # `artifacts/{appId}/users/{userId}/groceries`
        groceries_collection_ref = db.collection(f"artifacts/default-app-id/users/{user_id}/groceries")

        # Iterate through the items and save each one as a new document.
        for item in items_data:
            # We don't specify a document ID, so Firestore will generate one for us.
            groceries_collection_ref.add(item)
        
        return jsonify({"message": f"Successfully saved {len(items_data)} items to Firestore."}), 200

    except Exception as e:
        print(f"Error saving to Firestore: {e}")
        return jsonify({"error": f"An error occurred while saving to the database: {str(e)}"}), 500

if __name__ == '__main__':
    # When you run this script, it will start a local development server.
    # In production on a GCE instance, you would use a production-ready
    # server like Gunicorn or uWSGI.
    app.run(debug=True, host='0.0.0.0', port=5000)
