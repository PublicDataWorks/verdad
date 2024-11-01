# Verdad

Verdad is a Python-based project that captures audio streams, then processes the audio through a multistage pipeline for detecting suspected "snippets" of mis/disinfo, transcribe audio to text-with-timestamps, generate a short audio clip for each snippet, performs an analysis and finally stores all the structured output in a postgres database. 

## Development Setup

1. **Clone the repository:**

    ```bash
    git clone git@github.com:PublicDataWorks/verdad.git
    cd verdad
    ```

2. **Create a virtual environment:**

    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    ```

3. **Install the required dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

4. **Set up your environment variables:**
    - Rename `.env.sample` to `.env`.
    - Add your OpenAI API key to the `.env` file:
        ```plaintext
        OPENAI_API_KEY=your_openai_api_key_here
        ```

## Usage

To run the audio processing pipeline, execute the `main.py` script:

```bash
python verdad/src/main.py
```

By default, the script captures a 15-second audio stream from `https://securenetg.com/radio/8090/radio.aac`, transcribes it, and translates the transcription to English.

### Customizing Parameters

You can customize the URL and duration of the audio stream by modifying the parameters in the `main.py`:

```python
url = "https://securenetg.com/radio/8090/radio.aac"  # Your audio stream URL
duration_seconds = 15  # Duration for each audio segment
```

## Contributing

Contributions are welcome! Here are some ways you can contribute:

-   Report bugs and issues.
-   Suggest features and enhancements.
-   Submit pull requests with improvements.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) for more details.
