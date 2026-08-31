# python create_env.py - run this in the old laptop to get environment.yml folder. Change name to name: myenv
# new laptop - conda env create -f environment.yml   - ⏳ This downloads several GB and can take 15–45 minutes. 
# # next command - conda activate myenv
# next command - conda list

import subprocess

# Define the name you want for your new environment
env_name = "myenv"

# Run the conda command to export the current environment as a yml structure
# --no-builds keeps the file clean and cross-platform friendly
try:
    result = subprocess.run(
        ["conda", "env", "export", "--no-builds"], 
        capture_output=True, 
        text=True, 
        check=True
    )
    
    lines = result.stdout.splitlines()
    
    # Replace the original environment name with your custom one
    if lines:
        lines[0] = f"name: {env_name}"
        
    # Write it out to environment.yml
    with open("environment.yml", "w") as f:
        f.write("\n".join(lines) + "\n")
        
    print(f"Successfully created environment.yml with name '{env_name}'!")

except FileNotFoundError:
    print("Error: 'conda' command not found. Make sure you run this inside an Anaconda Prompt / terminal.")
except subprocess.CalledProcessError as e:
    print(f"Error exporting environment: {e.stderr}")