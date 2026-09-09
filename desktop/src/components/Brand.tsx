import markUrl from "../../../assets/sleipnir-mark.svg";

export function Brand() {
  return (
    <div className="brand" aria-label="Sleipnir">
      <img src={markUrl} alt="" />
      <span>
        <strong>SLEIPNIR</strong>
        <small>eight-lane orchestration</small>
      </span>
    </div>
  );
}
