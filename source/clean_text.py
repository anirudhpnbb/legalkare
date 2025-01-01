import os
import re
from bs4 import BeautifulSoup

def html_to_text(raw_html: str) -> str:
    """
    Converts HTML into a clean, plain-text format using Beautiful Soup.
    """
    soup = BeautifulSoup(raw_html, "html.parser")

    # Extract the text (separator helps keep some spacing between elements)
    text = soup.get_text(separator=" ")

    # Clean up multiple spaces, newlines, etc.
    text = re.sub(r"\s+", " ", text).strip()

    return text

def process_html_files(directory_path: str):
    """
    Loops over all files in the given directory. For each file:
      1) Reads its content
      2) Converts HTML to clean text
      3) Overwrites (replaces) the original file with the cleaned text
    """
    # List all files in the directory
    for filename in os.listdir(directory_path):
        # If your HTML files have a specific extension, check that here
        # e.g., if you know they have .html or .htm or .txt extension:
        if filename.lower().endswith(('.html', '.htm', '.txt')):
            file_path = os.path.join(directory_path, filename)

            # Read the raw HTML content
            with open(file_path, 'r', encoding='utf-8') as f:
                raw_html = f.read()

            # Convert HTML to cleaned text
            cleaned_text = html_to_text(raw_html)

            # Overwrite the file with cleaned text
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(cleaned_text)

            print(f"[+] Processed and replaced: {filename}")

if __name__ == "__main__":
    # Example usage:
    folder_with_html_files = "ik_downloads"
    process_html_files(folder_with_html_files)
