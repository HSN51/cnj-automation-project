#CNJ Automation Project

This project was developed to perform automated operations in the CNJ (Conselho Nacional de Justiça) system.

## Installation

1. Create a Python virtual environment:
```bash
python -m venv venv
```

2. Activate the virtual environment:
```bash
# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

3. Install the required packages:
```bash
pip install -r requirements.txt
```

4. Create the environment variables file:
```bash
cp .env.example .env
```

5. Update the values ​​in the `.env` file with your own information:
- `TWOCAPTCHA_API_KEY`: The API key you obtained from the 2Captcha service
- `USER_PROFILE_DIR`: The path to your Chrome user profile directory
- `DEFAULT_CPF`: The CPF number to use for testing
- `HEADLESS`: Run the browser in incognito mode not running

## Usage

```bash
python cnj_automation.py
```

## Requirements

- Python 3.7+
- Chrome/Chromium browser
- 2 Captcha accounts (for captcha solving)

## Security

- The `.env` file will not be uploaded to Git, and your API keys will remain private.
- Please do not share your API keys.

## License

This project is developed for educational purposes.
