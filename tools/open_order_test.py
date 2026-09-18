from pywinauto import Desktop


def find_fakturama():
    desktop = Desktop(backend="uia")

    matches = []

    for window in desktop.windows():
        try:
            info = window.element_info
            title = window.window_text()

            if (
                title.startswith("Fakturama")
                and info.class_name == "SWT_Window0"
            ):
                matches.append(window)
        except Exception:
            continue

    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one Fakturama window, found {len(matches)}"
        )

    return matches[0]


window = find_fakturama()

print("Connected to:")
print(window.window_text())


buttons = []

for control in window.descendants(control_type="Button"):
    try:
        if control.element_info.name == "Create: New Order":
            buttons.append(control)
    except Exception:
        pass


print(f"New Order matches: {len(buttons)}")

if len(buttons) != 1:
    raise RuntimeError(
        f"Expected exactly one New Order button, found {len(buttons)}"
    )


button = buttons[0]

print("Name:", button.element_info.name)
print("Type:", button.element_info.control_type)
print("Rectangle:", button.element_info.rectangle)
print("Enabled:", button.is_enabled())


print("\nOpening New Order...")

button.invoke()

print("New Order action invoked.")