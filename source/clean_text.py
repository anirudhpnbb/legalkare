import os
import re
from bs4 import BeautifulSoup

def html_to_text(raw_html: str) -> str:
    """
    Converts HTML into a plain-text format while preserving paragraphs,
    line breaks, and headings.
    """
    soup = BeautifulSoup(raw_html, "html.parser")

    # Remove script or style elements
    for element in soup(["script", "style"]):
        element.decompose()

    # Convert <br> to line breaks
    for br in soup.find_all("br"):
        br.replace_with("\n")

    # Convert <p> to double line breaks
    for p in soup.find_all("p"):
        p.insert_before("\n")
        p.append("\n")

    # Convert headings to blank lines before & after
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        heading.insert_before("\n")
        heading.append("\n")

    text = soup.get_text()

    # Collapse multiple blank lines
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()

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
