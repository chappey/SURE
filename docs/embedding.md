# Embedding EasyLearn in Canvas (iFrame & Cookies)

Modern browsers restrict third-party cookies (cookies set by an iframe from a domain different from the parent window). Because of this, embedding an LTI tool inside a Canvas iframe will block the OIDC state/nonce cookies and FastAPI session cookies, causing validation to fail with the error:

> Your browser prohibits to save cookies in the iframes. Click here to open content in the new tab.

To address this, apply one of the following integration methods:

---

## Method 1: Load in a New Tab / Window (Recommended)

By configuring the LTI Developer Key to launch the application in a new browser tab/window, it acts as a first-party application. The browser then allows cookies, and the handshake succeeds.

### Canvas Configuration Steps:
1. Log in to Canvas as an Administrator.
2. Go to **Admin** > **Developer Keys**.
3. Edit the **Developer Key** created for **EasyLearn**.
4. In the placement configurations (e.g., **Course Navigation**):
   * Set the **Window Target** option to `_blank` (or select **"New Window"** / **"Load in a new tab"** depending on your Canvas interface version).
5. Save the configuration.
6. When users click on the tool link, it will display a landing page to **"Load EasyLearn in a new window"** and open cleanly in a new tab.

---

## Method 2: Configure Same-Domain Hosting (Production Embedding)

If you require the application to be embedded inside the Canvas iframe directly:
1. Host the EasyLearn application on a subdomain of your institution's main Canvas domain.
   * *Example:* If Canvas is hosted on `canvas.university.edu`, host the LTI tool on `easylearn.university.edu`.
2. Because they share the same top-level domain (`university.edu`), browsers will categorize the cookies under first-party context policies and allow them.

---

## Method 3: Local Browser Exceptions (Testing/Development Only)

If you need to test the embedded iframe behavior on your local machine:
* **Chrome:** Go to `chrome://settings/cookies` and choose **"Allow third-party cookies"** (or add `localhost` to the allow list).
* **Safari:** Go to **Preferences** > **Privacy** and disable **"Prevent cross-site tracking"**.

> [!WARNING]
> Do not ask students or teachers to lower their browser privacy configurations for production environments. Use Method 1 or Method 2 instead.
