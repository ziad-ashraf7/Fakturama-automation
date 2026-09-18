from pywinauto import Desktop


def find_fakturama():
    desktop = Desktop(backend="uia")

    for window in desktop.windows():
        try:
            info = window.element_info
            title = window.window_text()

            if (
                title.startswith("Fakturama")
                and info.class_name == "SWT_Window0"
            ):
                return window

        except Exception:
            continue

    raise RuntimeError("Fakturama window not found")


window = find_fakturama()

controls = window.descendants()


def describe(index, control):
    info = control.element_info

    try:
        rect = info.rectangle
    except Exception:
        rect = None

    print(
        f"{index:03d} | "
        f"type={info.control_type!r:<14} | "
        f"name={info.name!r:<45} | "
        f"auto_id={info.automation_id!r:<15} | "
        f"class={info.class_name!r:<20} | "
        f"rect={rect}"
    )


print("=== ALL CONTROLS AROUND ADDRESSES ===")

for index in range(55, 82):
    if index < len(controls):
        try:
            describe(index, controls[index])
        except Exception as exc:
            print(index, "ERROR:", exc)


print("\n=== ALL CONTROLS AROUND ITEMS ===")

for index in range(72, 105):
    if index < len(controls):
        try:
            describe(index, controls[index])
        except Exception as exc:
            print(index, "ERROR:", exc)


print("\n=== CONTROL TYPES ===")

types = {}

for control in controls:
    try:
        control_type = control.element_info.control_type
        types[control_type] = types.get(control_type, 0) + 1
    except Exception:
        pass

for control_type, count in sorted(types.items()):
    print(f"{control_type!r}: {count}")