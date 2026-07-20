import subprocess

@service
def create_automation_by_ai(message=None):
    if not message:
        return
    # Run the shell command using standard python subprocess via task.executor
    task.executor(subprocess.run, f"echo '\n{message}\n' >> /config/automations.yaml", shell=True)

    # Reload automations
    automation.reload()
