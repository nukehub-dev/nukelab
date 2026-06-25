import { createFileRoute, Link } from '@tanstack/react-router'
import { ArrowLeft, UserCircle } from 'lucide-react'
import { motion } from 'framer-motion'
import { ProfilePage } from '../components/settings/profile-page'

export const Route = createFileRoute('/settings/profile')({
  component: ProfileSettingsPage,
})

function ProfileSettingsPage() {
  return (
    <div className="min-h-screen space-y-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-3 px-6 lg:px-10 pt-6 lg:pt-8"
      >
        <Link
          to="/settings"
          className="p-2 rounded-lg hover:bg-accent transition-colors shrink-0 inline-flex"
        >
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="p-2 rounded-xl bg-primary/10">
          <UserCircle className="w-5 h-5 text-primary" />
        </div>
        <div>
          <h1 className="text-xl font-bold">Profile</h1>
          <p className="text-sm text-muted-foreground">
            Manage your account information and avatar
          </p>
        </div>
      </motion.div>
      <div className="px-6 lg:px-10 pb-10">
        <ProfilePage />
      </div>
    </div>
  )
}
