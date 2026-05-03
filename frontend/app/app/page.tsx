export default function AppPage() {
  return (
    <main className="project-main">
      <div className="project-shell">
        <div className="project-copy">
          <p className="project-kicker">Main Frontend</p>
          <h1 className="project-title">
            Autonomous dataset engineering, in one workspace.
          </h1>
          <p className="project-description">
            This is the primary product surface for the Autonomous Dataset Agent:
            source discovery, frame curation, labeling, dataset building, YOLO
            training, evaluation, and metric-driven iteration.
          </p>
        </div>

        <div className="project-grid">
          <article className="project-card">
            <span className="project-card-label">01</span>
            <h2>Agent Pipeline</h2>
            <p>
              Specialized agents handle search, ranking, critique, labeling,
              training, evaluation, and retry planning with inspectable outputs.
            </p>
          </article>

          <article className="project-card">
            <span className="project-card-label">02</span>
            <h2>YOLO Dataset Loop</h2>
            <p>
              Curated frames and consistent annotations feed a trainable dataset
              that can be iterated as weak classes and failure modes are exposed.
            </p>
          </article>

          <article className="project-card">
            <span className="project-card-label">03</span>
            <h2>Metric-Driven Decisions</h2>
            <p>
              Evaluation results determine whether the system stops, relabels,
              rebalances, retrains, or collects more source material.
            </p>
          </article>
        </div>
      </div>
    </main>
  )
}
