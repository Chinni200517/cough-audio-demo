# Free Render deployment

1. Create a GitHub repository (for example cough-audio-demo).
2. Upload the contents of this deploy_render folder to the repository root. Keep the output folder and its files together. Dockerfile must be at the root.
3. Sign in to https://render.com and choose New > Web Service.
4. Connect the GitHub repository.
5. Select Docker as the language/runtime. Leave Root Directory empty.
6. Select the Free instance type ($0), then click Deploy Web Service.
7. Wait for Live and open the supplied https://YOUR-SERVICE.onrender.com URL.
8. Upload a short cough recording to verify prediction and report generation.

No build or start command is needed: Render uses the Dockerfile. The app reads Render's PORT environment variable and binds to 0.0.0.0.

Free-tier limitations: 512 MB RAM, service sleeps after 15 minutes without traffic, monthly free usage limits apply, and local history/reports are not persistent across restarts. Startup after sleeping can be slow. This container has not been built or tested on Render. If logs show out-of-memory errors, the app will need memory optimization to remain on the free tier.

Official instructions: https://render.com/docs/free and https://render.com/docs/docker
