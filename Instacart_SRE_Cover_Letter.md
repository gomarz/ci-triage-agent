Brandon Thomas
Tempe, AZ · 623-251-9208 · bra2091589@gmail.com · github.com/gomarz

---

Dear Hiring Team,

I spent three years at General Motors as a software engineer, and the part of the job I consistently liked most was the reliability work: owning the release process for internal developer tooling, and figuring out why integration runs failed when nobody could reproduce them. Your Site Reliability Engineer II posting describes that work as the job rather than the margins of it, which is why I'm applying.

At GM I ran the end-to-end release process for tooling used by multiple engineering and validation teams — preparing releases, driving review and approval, and publishing artifacts to Artifactory and our internal software center — while maintaining the GitHub Actions workflows in that path. Alongside that, I did root-cause analysis on failures across distributed test infrastructure and vehicle communication interfaces, where the recurring problem was separating real regressions from environment drift and flaky infrastructure. I also built Python automation that replaced manual setup work and cut environment setup time for validation runs by 30%. Most of what I did there was reducing toil and making failures reproducible.

I was laid off in April. Since then I've been building a service that triages CI failures automatically: it ingests GitHub Actions runs, clusters recurring failures, and proposes fixes verified by re-running the suite. It's running on AWS with Fargate, CDK, and OpenTelemetry tracing. It's early and I'd describe it as in progress rather than finished, but it's the direct extension of the manual triage I was doing at GM, and it's how I've been getting deeper into the infrastructure side.

I'll be straightforward about the gaps: I haven't written Ruby or Go professionally, and I don't have prior SRE-titled experience. What I do have is three years of release engineering, real debugging experience on systems that failed in confusing ways, and a five-year track record maintaining an open-source Java project where I triage crash reports from users and can't afford to break their existing data. Your posting emphasizes mentorship and growth, and I'd rather join a team where I can build depth deliberately than overstate what I know today.

Thank you for your consideration.

Brandon Thomas
