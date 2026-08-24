import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthProvider } from '../context/AuthContext';
import { EmailScanner } from './EmailScanner';

vi.mock('../utils/audio', () => ({ playCyberSFX: () => {} }));

const renderWithAuth = (ui: React.ReactNode) => render(<AuthProvider>{ui}</AuthProvider>);

describe('EmailScanner', () => {
  it('renders the forensics panel', async () => {
    renderWithAuth(<EmailScanner />);
    expect(await screen.findByText(/EMAIL FORENSICS/)).toBeInTheDocument();
  });

  it('loads the sample and shows a verdict with indicators (MSW-mocked API)', async () => {
    const user = userEvent.setup();
    renderWithAuth(<EmailScanner />);

    await user.click(screen.getByText(/load sample phishing email/i));
    await user.click(screen.getByRole('button', { name: /ANALYZE_MESSAGE/i }));

    // A concrete indicator + the verdict from the mocked forensics response.
    // (Exact 'phishing' avoids also matching the "load sample phishing email" link.)
    expect(await screen.findByText('LOOKALIKE_SENDER_DOMAIN')).toBeInTheDocument();
    expect(await screen.findByText('phishing')).toBeInTheDocument();
  });
});
