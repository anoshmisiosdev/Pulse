import { Link } from "react-router-dom";
import ChurnaryMark from "../components/ChurnaryMark";
import SeoHead from "../components/SeoHead";

export default function NotFound() {
  return (
    <div className="not-found">
      <SeoHead
        title="Page not found | Churnary"
        description="The page you requested could not be found. Return to Churnary customer retention."
        path="/404"
        noIndex
      />
      <style>{`
        .not-found { min-height: 100vh; display: grid; place-items: center; padding: 24px; background: #f4ecdf; color: #2a211c; }
        .not-found__card { width: min(680px,100%); border: 1px solid #ddcdb9; border-radius: 20px; background: #fffaf3; padding: clamp(32px,7vw,76px); box-shadow: 0 30px 80px rgba(59,42,32,.11); }
        .not-found__brand { display: inline-flex; align-items: center; gap: 10px; color: #2a211c; font: 700 20px var(--font-display); }
        .not-found__code { margin: 54px 0 0; color: #b4532a; font-size: 11px; font-weight: 850; letter-spacing: .16em; text-transform: uppercase; }
        .not-found h1 { max-width: 520px; margin: 12px 0 0; font-size: clamp(42px,8vw,72px); line-height: 1; letter-spacing: -.045em; }
        .not-found p { max-width: 500px; margin: 18px 0 0; color: #766253; font-size: 17px; line-height: 1.6; }
        .not-found__links { display: flex; flex-wrap: wrap; gap: 11px; margin-top: 30px; }
        .not-found__links a { border: 1px solid #b4532a; border-radius: 8px; padding: 12px 16px; color: #9d401f; font-weight: 800; text-decoration: none; }
        .not-found__links a:first-child { background: #b4532a; color: #fff; }
      `}</style>
      <section className="not-found__card">
        <div className="not-found__brand"><ChurnaryMark size={29} tile /> Churnary</div>
        <p className="not-found__code">404 · Page not found</p>
        <h1>This customer took a different route.</h1>
        <p>The page may have moved. The retention calculator and early-access page are still right where you need them.</p>
        <div className="not-found__links">
          <Link to="/">Return home</Link>
          <Link to="/customer-churn-risk-calculator">Open the calculator</Link>
        </div>
      </section>
    </div>
  );
}
