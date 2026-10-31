/** Public surface of voice — talk to the agent and hear it answer (Web Speech API, no backend). */
export { LangToggle } from "./lang-toggle";
export { MicButton, type MicButtonProps, UNSUPPORTED_HINT } from "./mic-button";
export { MicOrb } from "./mic-orb";
export { SpeakerToggle } from "./speaker-toggle";
export { guessLang, pickVoice, type VoiceLang } from "./speech-api";
export { useVoiceStore } from "./store";
export { type Speech, type Spoken, useSpeakArrivals, useSpeech } from "./use-speech";
export {
  type SpeechInput,
  type SpeechInputStatus,
  useSpeechInput,
  useSpeechRecognitionSupported,
} from "./use-speech-input";
