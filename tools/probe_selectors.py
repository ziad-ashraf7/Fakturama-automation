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
            f"Expected exactly one Fakturama window, "
            f"found {len(matches)}"
        )

    return matches[0]


def find_section_images(window, section_name: str):
    labels = []

    for control in window.descendants(control_type="Text"):
        try:
            if control.element_info.name == section_name:
                labels.append(control)
        except Exception:
            continue

    if len(labels) != 1:
        raise RuntimeError(
            f"Expected exactly one {section_name!r} label, "
            f"found {len(labels)}"
        )

    label = labels[0]
    parent = label.parent()

    print(f"\n=== {section_name} ===")
    print("Label rect:", label.element_info.rectangle)
    print("Parent type:", parent.element_info.control_type)
    print("Parent rect:", parent.element_info.rectangle)

    images = []

    for child in parent.children():
        try:
            if child.element_info.control_type == "Image":
                images.append(child)
        except Exception:
            continue

    images.sort(
        key=lambda image: image.element_info.rectangle.top
    )

    print(f"Images found: {len(images)}")

    for index, image in enumerate(images):
        info = image.element_info

        print(
            f"{index}: "
            f"auto_id={info.automation_id!r} "
            f"rect={info.rectangle}"
        )

    return images


window = find_fakturama()

address_images = find_section_images(
    window,
    "Addresses",
)

item_images = find_section_images(
    window,
    "Items",
)


print("\n=== EXPECTED SELECTORS ===")

if address_images:
    print(
        "Existing Debtor selector:",
        address_images[0].element_info.rectangle,
    )

if item_images:
    print(
        "Existing Product selector:",
        item_images[0].element_info.rectangle,
    )


# print("\nOpening existing Debtor selector...")

# address_images[0].click_input()


print("\nOpening existing Product selector...")

item_images[0].click_input()