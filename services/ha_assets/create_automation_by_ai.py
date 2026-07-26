def _append_yaml(path, text):
    # Ghi file thuần Python — KHÔNG qua shell. Bản cũ dùng
    # subprocess.run(f"echo '{message}' >> ...", shell=True): message do AI sinh
    # chứa dấu nháy / ; / $() là thành SHELL INJECTION ngay trong container HA.
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n" + str(text) + "\n")


@service
def create_automation_by_ai(message=None):
    if not message:
        return
    task.executor(_append_yaml, "/config/automations.yaml", message)

    # Reload automations
    automation.reload()
