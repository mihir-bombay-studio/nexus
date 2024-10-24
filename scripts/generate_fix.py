import os
import re
from openai import OpenAI
from github import Github
import difflib
import time
from swarm import Swarm, Agent

# Initialize Swarm client
swarm_client = Swarm()

# Get environment variables
github_token = os.getenv("PAT_TOKEN")
if not github_token:
    print("Error: PAT_TOKEN is not set.")
    exit(1)
else:
    print("PAT_TOKEN is set.")

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
if not openai_client:
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

# Context variables to pass to agents
context_variables = {
    'repo': repo,
    'issue': issue,
    'repo_type': repo_type,
    'all_file_paths': all_file_paths,
    'issue_title': issue_title,
    'issue_body': issue_body,
    'comments_text': comments_text,
}

# Define Agents

# Orchestrator Agent
def generate_code_changes(context_variables):
    issue_title = context_variables['issue_title']
    issue_body = context_variables['issue_body']
    comments_text = context_variables['comments_text']
    repo_type = context_variables['repo_type']
    all_file_paths = context_variables['all_file_paths']

    prompt = f"""
You are an AI assistant that helps fix issues in code repositories by generating code changes.

**Repository Type**: {repo_type}

**Repository Files**:
{all_file_paths}

**Issue to Resolve**:
Title: {issue_title}
Description: {issue_body}
Comments: {comments_text}

**Instructions**:

- Create or update files as needed to fix the issue.
- Provide code changes that can be directly applied to the codebase.
- Include accurate file paths and content.
- Respond **only** with the code changes in the following format:

File: path/to/file.extension
```
<rewritten_file content>
```

If multiple files need to be changed, separate them accordingly.

Do **not** include any explanations or additional text.

Ensure that the code is complete and not cut off.

If any of the specified files do not exist, adjust the code to fit within existing files.

**Important Restrictions**:

- Limit the response to **2000 tokens** to prevent output truncation.
- Do not mention any token limits or truncation in your response.
"""

    completion = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an AI assistant that generates code changes to fix issues in code repositories."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=1900,
        temperature=0,
    )

    generated_code = completion.choices[0].message.content.strip()

    # Print the generated code
    print("Generated Code:\n", generated_code)

    # Process the generated code to extract file paths and contents
    pattern = r'\*\*File\*\*:\s*(.*?)\s*```(?:[\w+]+)?\n(.*?)```'
    matches = re.findall(pattern, generated_code, re.DOTALL)

    if matches:
        processed_files = []
        for file_path, code_content in matches:
            file_path = file_path.strip()
            code_content = code_content.strip()

            # Fuzzy match file paths
            best_match = difflib.get_close_matches(file_path, all_file_paths, n=1, cutoff=0.5)
            if best_match:
                matched_file_path = best_match[0]
                processed_files.append((matched_file_path, code_content))
            else:
                print(f"No matching file found in repository: {file_path}")
                processed_files.append((file_path, code_content))
        context_variables['processed_files'] = processed_files
        return {'context_variables': context_variables}
    else:
        print("No code changes were generated.")
        return {'error': "No code changes were generated."}

orchestrator_agent = Agent(
    name="OrchestratorAgent",
    instructions="You generate code changes needed to fix issues in the repository.",
    functions=[generate_code_changes]
)

# Apply Changes Agent
def apply_code_changes(context_variables):
    processed_files = context_variables.get('processed_files', [])
    for file_path, code_content in processed_files:
        # Ensure directories exist
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # Write content to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(code_content)
        print(f"Changes applied to {file_path}")
    return "Code changes have been applied."

apply_changes_agent = Agent(
    name="ApplyChangesAgent",
    instructions="You apply the generated code changes to the repository files.",
    functions=[apply_code_changes]
)

# Main Agent to coordinate the process
def main_agent_handler(context_variables):
    # Run the orchestrator agent to generate code changes
    swarm_client.run(
        agent=orchestrator_agent,
        messages=[],
        context_variables=context_variables
    )
    # Run the apply changes agent to apply the changes
    swarm_client.run(
        agent=apply_changes_agent,
        messages=[],
        context_variables=context_variables
    )
    return "Process completed."

main_agent = Agent(
    name="MainAgent",
    instructions="You coordinate the process of fixing issues by generating and applying code changes.",
    functions=[main_agent_handler]
)

# Run the main agent
response = swarm_client.run(
    agent=main_agent,
    messages=[],
    context_variables=context_variables
)

print("All code changes have been generated and saved.")
