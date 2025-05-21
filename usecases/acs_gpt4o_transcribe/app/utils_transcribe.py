import pyaudio


def list_audio_input_devices() -> None:
    """
    Print all available input devices (microphones) for user selection.
    """
    p = pyaudio.PyAudio()
    print("\nAvailable audio input devices:")
    for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        if dev["maxInputChannels"] > 0:
            print(f"{i}: {dev['name']}")
    p.terminate()


def choose_audio_device(predefined_index: int = None) -> int:
    """
    Return the index of the selected audio input device.
    If predefined_index is provided and valid, use it.
    Otherwise, prompt user if multiple devices are available.
    """
    p = pyaudio.PyAudio()
    try:
        mic_indices = [
            i
            for i in range(p.get_device_count())
            if p.get_device_info_by_index(i)["maxInputChannels"] > 0
        ]
        if not mic_indices:
            raise RuntimeError("❌ No audio input (microphone) devices found.")

        if predefined_index is not None:
            if predefined_index in mic_indices:
                print(f"🎤 Using predefined audio input device: {predefined_index}")
                return predefined_index
            else:
                print(f"Provided index {predefined_index} is not a valid input device.")

        if len(mic_indices) == 1:
            print(f"🎤 Only one audio input device found: {mic_indices[0]}")
            return mic_indices[0]

        print("Available audio input devices:")
        for idx in mic_indices:
            info = p.get_device_info_by_index(idx)
            print(f"  [{idx}]: {info['name']}")
        while True:
            try:
                selection = input(
                    f"Select audio input device index [{mic_indices[0]}]: "
                ).strip()
                if selection == "":
                    return mic_indices[0]
                selected_index = int(selection)
                if selected_index in mic_indices:
                    return selected_index
                print(
                    f"Index {selected_index} is not valid. Please choose from {mic_indices}."
                )
            except ValueError:
                print("Invalid input. Please enter a valid integer index.")

    finally:
        p.terminate()
