import { useRunStatus } from "./store";
import { ConfigScreen } from "./components/ConfigScreen";
import { OpsRoom } from "./components/OpsRoom";
import "./styles/crt.css";

function App() {
  const status = useRunStatus();
  return status === "config" ? <ConfigScreen /> : <OpsRoom />;
}

export default App;
