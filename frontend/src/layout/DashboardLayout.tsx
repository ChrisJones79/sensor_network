import { ReactNode } from 'react';

interface Props {
  left: ReactNode;
  right: ReactNode;
}

export default function DashboardLayout({ left, right }: Props) {
  return (
    <main className="dashboard-root">
      {left}
      <section className="right-panel">{right}</section>
    </main>
  );
}
