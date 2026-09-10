## Gemini on the existing Render service

Deploy the repository root to use the current Gemini chatbot in frontend_ui.py.
In Render > cough-audio-demo > Environment, set GEMINI_API_KEY to your Google AI
Studio key and GEMINI_MODEL to gemini-2.5-flash-lite, then choose Save and deploy.
GOOGLE_API_KEY is also accepted when GEMINI_API_KEY is absent. Never commit keys.
Adding a key name to render.yaml alone does not supply its secret value to an
existing service created manually.

If the configured model returns HTTP 404, the chatbot now lists models available
to the same key and retries with up to two stable Flash text models, preferring
Flash-Lite. It excludes Pro, preview, image and audio models. Discovery is cached
for five minutes. Authentication and quota errors do not trigger model switching.
Model discovery reference: https://ai.google.dev/api/models

After the latest code deploys, send a general question to the assistant. If it
uses local help, check Render Logs for aerova.gemini messages: missing key,
HTTP 403 (permissions), 404 (model unavailable), 429 (quota), connection timeout,
or no usable candidate. Logs omit API keys, questions, and response bodies.

Environment setup: https://render.com/docs/configure-environment-variables
Gemini thinking/output budget: https://ai.google.dev/gemini-api/docs/generate-content/thinking

UPDATE: Hugging Face now requires a paid plan for new Gradio/Docker Spaces. For a free option, use deploy_render/README.md. The Hugging Face instructions below are not a free deployment path.

Run locally (PowerShell, from this project folder):

```powershell
.\.venv\Scripts\python.exe gradio_app.py
```

Open http://127.0.0.1:7860 and upload a cough recording.

Deploy on Hugging Face Spaces:

1. Sign in at https://huggingface.co and choose New Space.
2. Enter a name, such as cough-audio-demo.
3. Choose Docker as the SDK and a blank template. Select CPU hardware; check the displayed price before choosing it.
4. Create the Space and open Files, then Add file / Upload files.
5. Upload the CONTENTS of deploy_huggingface into the Space root. Keep output as a subfolder. Dockerfile and README.md must be at the root, not inside deploy_huggingface.
6. Commit the files and watch the build logs. When the status becomes Running, open the App tab and upload audio.
7. Share your Space URL: https://huggingface.co/spaces/YOUR_USERNAME/YOUR_SPACE_NAME.

The deployment folder includes the app, compatible model artifacts, a Dockerfile, and package versions from the working local environment. It excludes local assessment history and the training dataset. Docker is unavailable on this machine, so the Linux image build has not been tested. The original root requirements.txt is outdated for the current UI; use the prepared folder for deployment.

Space runtime files, including generated reports/history, are temporary unless you configure persistent storage. This is an AEROVA research demo; model confidence is not a medical diagnosis. The email/password screen and arithmetic CAPTCHA are a demo access gate, not verified account authentication or production bot protection.

Official guide: https://huggingface.co/docs/hub/spaces-sdks-docker

Fresh execution outputs are in run_results. Notebook code cells were executed with Python and a noninteractive plotting backend; charts are saved as PNG files in the project root. The Phase 3/4 and summary notebooks read existing model scores; fresh retraining artifacts and scores are separately saved in run_results/retrained_models.
