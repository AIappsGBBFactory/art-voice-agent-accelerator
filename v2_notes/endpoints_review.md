

### review of /media.py

from imports
- acs auth is not being used (this should be getting used)
    - manage as an adapter
- streamingspeechrecognizerfrombytes not being used
- old lvagent stuff should be stripped
- currently structured to accommodate for /realtime voice live orchestration via the `_resolve_call_stream_mode`

- rename ACS_STREAMING_MODE to something else
    - it should be somewhat generic, currently we support voicelive, acs media - but transcription should also be added



    Voice Live (Speech) > binary 
    Realtime Transcription (ACS + Speech) > Text based - feed directly into llm, custom adapter?
    Realtime Media Stream (Speech) > binary

    Voice Live adapter (sits more on the agent side though...)
    - Custom event hanlders
    - Custom cancellation signal

    ACS adapter
    - wrapping the websocket (i.e AudioData)
    - Custom client cancellation signal
    - Custom event handlers



Adapter types:
- Client orchestration adapaters
    - Client = frontend UI, ACS, Voice Live
- Agent adapters


- need for a unified event mapper?
    - allow for overloading, simplify which events should be emitted and how (i.e envelope types)
    - Core standard events to design around:
        - User input recognition partial deltas (transcribed text)
        - User input recognition completed transcription
            - on_partial, on_final
        - User input started
        - User input ended

        - Response transcription delta
        - Response transcription completed

        - Response started
        - Response ended
        - Catchall for Errors
            - adapater specific error handling here?

- Redis session storage structure
    - session:<session_id>
    - session:<session_id>:session_config
    - session:<session_id>:

    - calls:<call_id>
        - map the session_id here, and session ids
        - map the demo identity associated with number? might be worth just handling this part in the cosmosdb


- CsomosDB - better utilization
    - Standardize on structure/consolidate a generic base for use with many different scenarios
        - identity table <--> scenario-specific attributes
    - store previous call histories, summaries, sentiment analysis, etc.
        - more to flush out on the post call processing logic side?
