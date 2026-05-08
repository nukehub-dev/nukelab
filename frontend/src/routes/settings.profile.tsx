import { createFileRoute } from '@tanstack/react-router';
import { ProfilePage } from '../components/settings/profile-page';

export const Route = createFileRoute('/settings/profile')({
  component: ProfilePage,
});
