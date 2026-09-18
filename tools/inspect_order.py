from pywinauto import Desktop


desktop = Desktop(backend="uia")

fakturama = None

for window in desktop.windows():
    try:
        info = window.element_info
        title = window.window_text()

        if (
            title.startswith("Fakturama")
            and info.class_name == "SWT_Window0"
        ):
            fakturama = window
            break
    except Exception:
        continue


if fakturama is None:
    raise RuntimeError("Fakturama not found")


controls = fakturama.descendants()

print(f"Total controls: {len(controls)}")
print("=" * 140)


interesting = {
    "Button",
    "Edit",
    "ComboBox",
    "Table",
    "DataGrid",
    "Text",
    "Tab",
    "TabItem",
    "CheckBox",
    "RadioButton",
    "MenuItem",
    "SplitButton",
}


for index, control in enumerate(controls):
    try:
        info = control.element_info

        if info.control_type not in interesting:
            continue

        print(
            f"{index:03d} | "
            f"type={info.control_type!r:<14} | "
            f"name={info.name!r:<45} | "
            f"auto_id={info.automation_id!r:<20} | "
            f"class={info.class_name!r}"
        )

    except Exception:
        pass