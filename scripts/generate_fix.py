import os
import re
from openai import OpenAI
from github import Github
import difflib

# Get environment variables
github_token = os.getenv("PAT_TOKEN")
if not github_token:
    print("Error: PAT_TOKEN is not set.")
    exit(1)
else:
    print("PAT_TOKEN is set.")

# Note: Retain the use of 'gpt-4o' as it is the latest model
# Remember to use 'gpt-4o' in future code updates
# DO NOT REMOVE THIS COMMENT
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
if not client:
    print("Error: OPENAI_API_KEY is not set.")
    exit(1)
else:
    print("OPENAI_API_KEY is set.")

repo_name = os.getenv("REPO_NAME")
if not repo_name:
    print("Error: REPO_NAME is not set.")
    exit(1)
else:
    print(f"Repository Name: {repo_name}")

issue_number = os.getenv("ISSUE_NUMBER")
if not issue_number:
    print("Error: ISSUE_NUMBER is not set.")
    exit(1)
else:
    print(f"Issue Number: {issue_number}")

# Authenticate with GitHub
g = Github(github_token)
repo = g.get_repo(repo_name)
issue = repo.get_issue(int(issue_number))

# Function to get all file paths in the repository
def get_all_file_paths(repo):
    file_paths = []
    contents = repo.get_contents("")
    while contents:
        file_content = contents.pop(0)
        if file_content.type == "dir":
            contents.extend(repo.get_contents(file_content.path))
        else:
            file_paths.append(file_content.path)
    return file_paths

# Identify repository type
def identify_repository_type(repo):
    file_paths = get_all_file_paths(repo)
    # Simple heuristic to determine repository type
    if any("config/settings_schema.json" in path for path in file_paths) or \
       any(dir_name in path for dir_name in ["assets", "layout", "templates"] for path in file_paths):
        return "Shopify Theme"
    elif any("package.json" in path for path in file_paths):
        return "Node.js"
    elif any("requirements.txt" in path for path in file_paths):
        return "Python"
    elif any("Gemfile" in path for path in file_paths):
        return "Ruby"
    elif any("pom.xml" in path for path in file_paths):
        return "Java"
    elif any("Cargo.toml" in path for path in file_paths):
        return "Rust"
    elif any("go.mod" in path for path in file_paths):
        return "Go"
    else:
        return "Unknown"

# Identify repository type
repo_type = identify_repository_type(repo)
print(f"Repository Type: {repo_type}")

# Get issue details
issue_title = issue.title
issue_body = issue.body or ""
comments = issue.get_comments()
comments_text = "\n".join([comment.body for comment in comments])

# Get all file paths from the repository
all_file_paths = get_all_file_paths(repo)

# Prepare the prompt for OpenAI
prompt = rf"""
You are an AI assistant that helps fix issues in code repositories.

**Repository Type**: {repo_type}

**Issue Title**:
{issue_title}

**Issue Description**:
{issue_body}

**Comments**:
{comments_text}

**Instructions**:

- Generate the code changes needed to fix the issue.
- Provide code changes that can be directly applied to the codebase.
- Include accurate file paths and content.
- Respond **only** with the code changes in the following format:

File: path/to/file.extension
\`\`\`
<file content>
\`\`\`

If multiple files need to be changed, separate them accordingly.

Do not include any explanations or additional text.

Ensure that the code is complete and not cut off.
"""

print("Prompt prepared for OpenAI.")

# Function to generate code changes with consensus building
def generate_code_changes(prompt, max_iterations=3):
    for iteration in range(max_iterations):
        print(f"Iteration {iteration + 1} of {max_iterations}")
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an AI assistant that helps fix issues in code repositories."
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2000,
                temperature=0,
            )
            generated_code = response.choices[0].message.content.strip()
            print("Received response from OpenAI.")
            # Debugging: Print the generated code
            print("Generated Code:")
            print(generated_code)

            # Regex to match file paths and code blocks
            pattern = r'File:\s*(.*?)\s*```(?:[\w+\s]*)\n(.*?)```'

            matches = re.findall(pattern, generated_code, re.DOTALL)

            # Debugging: Print the matches
            print("Matches found:")
            print(matches)

            if not matches:
                print("No code changes were generated.")
                continue

            matched_files = []
            for file_path, code_content in matches:
                file_path = file_path.strip()
                code_content = code_content.strip()

                # Fuzzy match file paths
                best_match = difflib.get_close_matches(file_path, all_file_paths, n=1, cutoff=0.5)
                if best_match:
                    matched_file_path = best_match[0]
                    matched_files.append((matched_file_path, code_content))
                else:
                    print(f"No matching file found in repository for: {file_path}")
                    matched_files.append((file_path, code_content))  # Allow creation of new files if needed

            if matched_files:
                return matched_files
            else:
                print("No matching files found. Adjusting prompt for next iteration.")

                # Adjust the prompt to include information about missing files
                missing_files = [fp for fp, _ in matches if not difflib.get_close_matches(fp, all_file_paths, n=1, cutoff=0.5)]
                prompt_adjustment = f"\nNote: The files {missing_files} do not exist in the repository. Please only use existing files."

                prompt += prompt_adjustment

        except Exception as e:
            print(f"Error calling OpenAI API: {e}")
            continue
    print("Failed to generate valid code changes after multiple iterations.")
    exit(1)

# Generate code changes with consensus building
matched_files = generate_code_changes(prompt, max_iterations=3)

# Process the matched files
for file_path, code_content in matched_files:
    file_path = file_path.strip()
    code_content = code_content.strip()

    existing_content = ''
    # Read existing file content if it exists
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            existing_content = f.read()
    else:
        print(f"File {file_path} does not exist locally. Creating new file.")

    # Analyze and apply changes
    analysis_prompt = f"""
You are assisting in integrating code changes into existing files.

- Existing Content:
{existing_content}

- Proposed Changes:
{code_content}

Based on the existing content and the proposed changes, generate the final content for the file.

Provide **only** the updated file content, without any explanations or additional text.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "You are an AI assistant that helps integrate code changes contextually."
                },
                {"role": "user", "content": analysis_prompt}
            ],
            max_tokens=1500,
            temperature=0,
        )
        final_content = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error calling OpenAI API for analysis: {e}")
        final_content = code_content

    print(f"Processing file: {file_path}")
    print("Existing Content:")
    print(existing_content)
    print("Final Content:")
    print(final_content)

    if existing_content != final_content:
        dir_name = os.path.dirname(file_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        # Handle case where dir_name is empty (i.e., file is in the current directory)
        with open(file_path, 'w') as f:
            f.write(final_content)
        print(f"Generated file: {file_path}")
    else:
        print(f"No changes detected for file: {file_path}")

print("Code changes have been generated and saved.")
