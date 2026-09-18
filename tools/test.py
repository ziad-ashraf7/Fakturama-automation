from pywinauto import Desktop


desktop = Desktop(backend="uia")

fakturama = None

for window in desktop.windows():
    try:
        title = window.window_text()
        info = window.element_info

        if (
            title.startswith("Fakturama")
            and info.class_name == "SWT_Window0"
        ):
            fakturama = window
            break

    except Exception:
        continue


if fakturama is None:
    raise RuntimeError("Could not find Fakturama window")


print("=== FAKTURAMA WINDOW ===")
print("Title:", repr(fakturama.window_text()))
print("Visible:", fakturama.is_visible())
print("Enabled:", fakturama.is_enabled())
print("Handle:", fakturama.handle)
print("Class:", fakturama.element_info.class_name)
print("Process ID:", fakturama.element_info.process_id)


print("\n=== DESCENDANT CONTROLS ===")

controls = fakturama.descendants()

print(f"Total controls found: {len(controls)}")
print("=" * 120)

for index, control in enumerate(controls):
    try:
        info = control.element_info

        print(
            f"{index:03d} | "
            f"type={info.control_type!r:<15} | "
            f"name={info.name!r:<40} | "
            f"auto_id={info.automation_id!r:<25} | "
            f"class={info.class_name!r}"
        )

    except Exception as exc:
        print(f"{index:03d} | ERROR: {exc}")