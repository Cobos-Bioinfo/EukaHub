/** EukaHub's privacy policy. Plain language, honest about the little we collect.
 *  Modeled on the sibling Annotrieve policy (both are read-only, account-free
 *  tools hosted at CRG). Prose is intentionally static, nothing is fetched.
 *  The data-protection contact is a placeholder until the CRG deployment. */

const UPDATED = "1 September 2026";
const CONTACT_EMAIL = "placeholder@crg.eu";

export default function Privacy() {
  return (
    <section className="legal">
      <h1 className="legal__title">Privacy policy</h1>
      <p className="legal__updated">Last updated {UPDATED}</p>

      <p className="legal__lede">
        EukaHub is a public, read-only tool for exploring how much genomic data exists across the
        eukaryotic tree of life. It has no accounts, no logins, and no advertising. We collect the
        minimum needed to run the service and understand how it is used. This page explains what
        that means.
      </p>

      <div className="legal__section">
        <h2 className="legal__h">What we collect</h2>
        <p>
          When you open a page or call the API, our web server records the standard technical
          details every web server logs: your IP address, the requested address and method, the
          response status, a timestamp, how long the response took, and your browser's user-agent
          and referring page.
        </p>
        <p>
          EukaHub has no login. It does not ask for your name, email, or any other personal detail
          to use it, and it does not create an account or a profile for you.
        </p>
      </div>

      <div className="legal__section">
        <h2 className="legal__h">Cookies and browser storage</h2>
        <p>
          EukaHub does not use cookies, and it runs no third-party analytics or tracking scripts.
        </p>
        <p>
          Your browser keeps a few small preferences on your device, such as your light or dark
          theme choice and where you have drilled on the data map. This stays in your browser, is
          never sent to our servers, and you can clear it at any time through your browser settings.
        </p>
      </div>

      <div className="legal__section">
        <h2 className="legal__h">How we use server logs</h2>
        <p>We use access logs only to run and improve the service:</p>
        <ul className="legal__list">
          <li>to understand overall usage, such as which countries traffic comes from,</li>
          <li>to monitor performance and diagnose errors, and</li>
          <li>to gauge the tool's reach for research.</li>
        </ul>
        <p>
          We do not use this data for advertising, we do not sell or share it, and we do not build
          profiles of individual users. Detailed logs are kept for a limited period, typically a few
          months, after which they are deleted or reduced to aggregate statistics that do not
          identify anyone.
        </p>
      </div>

      <div className="legal__section">
        <h2 className="legal__h">Feedback</h2>
        <p>
          If you choose to send feedback through the "Send feedback" link in the header menu, your
          message is filed as an issue in the project's public code repository on GitHub. The text
          you submit becomes publicly visible there, so please do not include anything you would not
          want made public.
        </p>
        <p>
          The feedback form has an optional email field. If you fill it in, it stays in the private
          form responses so we can follow up, and it is not published in the public issue. The form
          is a Google Form, so Google and GitHub each handle this data under their own privacy
          policies.
        </p>
      </div>

      <div className="legal__section">
        <h2 className="legal__h">Links to other services</h2>
        <p>
          EukaHub links out to external databases, including NCBI, ENA, and Annotrieve, so you can
          reach the original records. When you follow those links you leave EukaHub, and each
          service's own privacy policy applies.
        </p>
        <p>
          The short "About" summaries shown for some groups come from Wikipedia. EukaHub fetches
          them on the server, so your browser does not contact Wikipedia directly when you view them.
        </p>
      </div>

      <div className="legal__section">
        <h2 className="legal__h">Where the service runs</h2>
        <p>
          EukaHub is hosted at the Centre for Genomic Regulation (CRG) in Barcelona, Spain, within
          the European Union. Any personal data contained in server logs is handled in line with the
          EU General Data Protection Regulation (GDPR).
        </p>
      </div>

      <div className="legal__section">
        <h2 className="legal__h">Your rights</h2>
        <p>
          Under the GDPR you can ask to access the personal data we hold about you, to have it
          corrected or erased, to restrict or object to how it is processed, and to receive a copy
          of it. To exercise any of these rights, or if you have questions about this policy, contact
          us using the details below. We aim to respond within 30 days.
        </p>
      </div>

      <div className="legal__section">
        <h2 className="legal__h">Contact</h2>
        <p>
          Data protection contact: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
        </p>
      </div>

      <div className="legal__section">
        <h2 className="legal__h">Changes to this policy</h2>
        <p>
          We may update this policy as the service develops. The date at the top of the page shows
          when it was last changed.
        </p>
      </div>
    </section>
  );
}
