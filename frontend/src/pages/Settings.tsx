import { useState, useEffect } from 'react'
import { useSettings, useUpdateSettings } from '@/hooks/useSettings'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { toast } from 'sonner'
import type { Settings } from '@/types'

// Helper to safely parse settings from API (which returns strings)
function parseSettings(raw: Record<string, string>): Settings {
  return {
    max_streams_per_account_per_day: parseInt(raw.max_streams_per_account_per_day || '40', 10),
    min_stream_duration_sec: parseInt(raw.min_stream_duration_sec || '30', 10),
    max_concurrent_streams: parseInt(raw.max_concurrent_streams || '14', 10),
    rotation_interval_streams: parseInt(raw.rotation_interval_streams || '15', 10),
    rotation_interval_hours: parseInt(raw.rotation_interval_hours || '4', 10),
    cooldown_hours: parseInt(raw.cooldown_hours || '6', 10),
    humanization_level: (raw.humanization_level || 'medium') as Settings['humanization_level'],
    humanization_enabled: raw.humanization_enabled !== 'false',
    humanization_preset: (raw.humanization_preset || raw.humanization_level || 'medium') as Settings['humanization_preset'],
    pre_stream_min_sec: parseInt(raw.pre_stream_min_sec || '180', 10),
    pre_stream_max_sec: parseInt(raw.pre_stream_max_sec || '300', 10),
    between_tracks_min_sec: parseInt(raw.between_tracks_min_sec || '5', 10),
    between_tracks_max_sec: parseInt(raw.between_tracks_max_sec || '15', 10),
    random_actions_enabled: raw.random_actions_enabled !== 'false',
    min_actions_per_stream: parseInt(raw.min_actions_per_stream || '0', 10),
    max_actions_per_stream: parseInt(raw.max_actions_per_stream || '3', 10),
    warmup_between_tracks_min_sec: parseInt(raw.warmup_between_tracks_min_sec || '3', 10),
    warmup_between_tracks_max_sec: parseInt(raw.warmup_between_tracks_max_sec || '10', 10),
    default_account_type: (raw.default_account_type || 'free') as Settings['default_account_type'],
    warmup_duration_days: parseInt(raw.warmup_duration_days || '5', 10),
    creation_delay_min_sec: parseInt(raw.creation_delay_min_sec || '180', 10),
    creation_delay_max_sec: parseInt(raw.creation_delay_max_sec || '300', 10),
    daily_account_creation_cap: parseInt(raw.daily_account_creation_cap || '8', 10),
    daily_reset_hour: parseInt(raw.daily_reset_hour || '0', 10),
  }
}

// Helper to convert Settings to raw strings for API
function settingsToRaw(settings: Settings): Record<string, string> {
  return {
    max_streams_per_account_per_day: settings.max_streams_per_account_per_day.toString(),
    min_stream_duration_sec: settings.min_stream_duration_sec.toString(),
    max_concurrent_streams: settings.max_concurrent_streams.toString(),
    rotation_interval_streams: settings.rotation_interval_streams.toString(),
    rotation_interval_hours: settings.rotation_interval_hours.toString(),
    cooldown_hours: settings.cooldown_hours.toString(),
    humanization_level: settings.humanization_level,
    humanization_enabled: settings.humanization_enabled.toString(),
    humanization_preset: settings.humanization_preset,
    pre_stream_min_sec: settings.pre_stream_min_sec.toString(),
    pre_stream_max_sec: settings.pre_stream_max_sec.toString(),
    between_tracks_min_sec: settings.between_tracks_min_sec.toString(),
    between_tracks_max_sec: settings.between_tracks_max_sec.toString(),
    random_actions_enabled: settings.random_actions_enabled.toString(),
    min_actions_per_stream: settings.min_actions_per_stream.toString(),
    max_actions_per_stream: settings.max_actions_per_stream.toString(),
    warmup_between_tracks_min_sec: settings.warmup_between_tracks_min_sec.toString(),
    warmup_between_tracks_max_sec: settings.warmup_between_tracks_max_sec.toString(),
    default_account_type: settings.default_account_type,
    warmup_duration_days: settings.warmup_duration_days.toString(),
    creation_delay_min_sec: settings.creation_delay_min_sec.toString(),
    creation_delay_max_sec: settings.creation_delay_max_sec.toString(),
    daily_account_creation_cap: settings.daily_account_creation_cap.toString(),
    daily_reset_hour: settings.daily_reset_hour.toString(),
  }
}

// Preset defaults for applying when preset changes
const PRESET_DEFAULTS: Record<string, Partial<Settings>> = {
  low: {
    pre_stream_min_sec: 60,
    pre_stream_max_sec: 120,
    between_tracks_min_sec: 1,
    between_tracks_max_sec: 3,
    random_actions_enabled: false,
    min_actions_per_stream: 0,
    max_actions_per_stream: 1,
    warmup_between_tracks_min_sec: 1,
    warmup_between_tracks_max_sec: 2,
  },
  medium: {
    pre_stream_min_sec: 180,
    pre_stream_max_sec: 300,
    between_tracks_min_sec: 5,
    between_tracks_max_sec: 15,
    random_actions_enabled: true,
    min_actions_per_stream: 0,
    max_actions_per_stream: 3,
    warmup_between_tracks_min_sec: 3,
    warmup_between_tracks_max_sec: 10,
  },
  high: {
    pre_stream_min_sec: 300,
    pre_stream_max_sec: 480,
    between_tracks_min_sec: 10,
    between_tracks_max_sec: 30,
    random_actions_enabled: true,
    min_actions_per_stream: 1,
    max_actions_per_stream: 5,
    warmup_between_tracks_min_sec: 5,
    warmup_between_tracks_max_sec: 15,
  },
}

export function Settings() {
  const { data: settingsData, isPending, isError, refetch } = useSettings()
  const updateSettings = useUpdateSettings()

  // Local draft state for editing
  const [draft, setDraft] = useState<Settings | null>(null)
  const [hasChanges, setHasChanges] = useState(false)

  // Initialize draft when settings load
  useEffect(() => {
    if (settingsData?.settings) {
      const parsed = parseSettings(settingsData.settings)
      setDraft(parsed)
      setHasChanges(false)
    }
  }, [settingsData])

  const handleSave = async () => {
    if (!draft) return
    try {
      const rawSettings = settingsToRaw(draft)
      await updateSettings.mutateAsync({ settings: rawSettings })
      toast.success('Settings saved')
      setHasChanges(false)
    } catch (error) {
      toast.error('Failed to save settings')
    }
  }

  const handleReset = () => {
    if (settingsData?.settings) {
      const parsed = parseSettings(settingsData.settings)
      setDraft(parsed)
      setHasChanges(false)
      toast.info('Changes discarded')
    }
  }

  const updateField = <K extends keyof Settings>(key: K, value: Settings[K]) => {
    if (!draft) return
    setDraft(prev => prev ? { ...prev, [key]: value } : null)
    setHasChanges(true)
  }

  const handlePresetChange = (preset: Settings['humanization_preset']) => {
    if (!draft) return

    const defaults = PRESET_DEFAULTS[preset]
    if (defaults) {
      setDraft(prev => prev ? {
        ...prev,
        humanization_preset: preset,
        humanization_level: preset as Settings['humanization_level'],
        ...defaults,
      } : null)
    } else {
      // Custom preset - just update the preset field
      setDraft(prev => prev ? {
        ...prev,
        humanization_preset: preset,
      } : null)
    }
    setHasChanges(true)
  }

  // Mark as custom if advanced values deviate from preset
  const checkCustomPreset = (newDraft: Settings) => {
    const currentPreset = newDraft.humanization_preset
    if (currentPreset === 'custom') return

    const defaults = PRESET_DEFAULTS[currentPreset]
    if (!defaults) return

    const isDeviated =
      newDraft.pre_stream_min_sec !== defaults.pre_stream_min_sec ||
      newDraft.pre_stream_max_sec !== defaults.pre_stream_max_sec ||
      newDraft.between_tracks_min_sec !== defaults.between_tracks_min_sec ||
      newDraft.between_tracks_max_sec !== defaults.between_tracks_max_sec ||
      newDraft.random_actions_enabled !== defaults.random_actions_enabled ||
      newDraft.min_actions_per_stream !== defaults.min_actions_per_stream ||
      newDraft.max_actions_per_stream !== defaults.max_actions_per_stream ||
      newDraft.warmup_between_tracks_min_sec !== defaults.warmup_between_tracks_min_sec ||
      newDraft.warmup_between_tracks_max_sec !== defaults.warmup_between_tracks_max_sec

    if (isDeviated) {
      setDraft(prev => prev ? { ...prev, humanization_preset: 'custom' } : null)
    }
  }

  if (isPending) {
    return <div>Loading settings...</div>
  }

  if (isError || !draft) {
    return (
      <div className="space-y-4">
        <h1 className="text-3xl font-bold text-foreground">Settings</h1>
        <Card>
          <CardContent className="space-y-4 p-6">
            <div className="text-sm text-muted-foreground">
              Failed to load settings. Make sure the backend API is running, then try again.
            </div>
            <div>
              <Button onClick={() => void refetch()} className="bg-spotify hover:bg-spotify-dark">
                Retry
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold text-foreground">Settings</h1>
        {hasChanges && (
          <div className="text-sm text-yellow-500 font-medium">
            Unsaved changes
          </div>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Streaming Settings */}
        <Card>
          <CardHeader>
            <CardTitle>Streaming</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Max Streams Per Account Per Day</Label>
              <Input
                type="number"
                value={draft.max_streams_per_account_per_day}
                onChange={(e) => updateField('max_streams_per_account_per_day', parseInt(e.target.value, 10) || 0)}
              />
            </div>
            <div className="space-y-2">
              <Label>Min Stream Duration (sec)</Label>
              <Input
                type="number"
                value={draft.min_stream_duration_sec}
                onChange={(e) => updateField('min_stream_duration_sec', parseInt(e.target.value, 10) || 0)}
              />
            </div>
            <div className="space-y-2">
              <Label>Max Concurrent Streams</Label>
              <Input
                type="number"
                value={draft.max_concurrent_streams}
                onChange={(e) => updateField('max_concurrent_streams', parseInt(e.target.value, 10) || 0)}
              />
            </div>
          </CardContent>
        </Card>

        {/* Rotation Settings */}
        <Card>
          <CardHeader>
            <CardTitle>Rotation</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Rotation Interval (streams)</Label>
              <Input
                type="number"
                value={draft.rotation_interval_streams}
                onChange={(e) => updateField('rotation_interval_streams', parseInt(e.target.value, 10) || 0)}
              />
            </div>
            <div className="space-y-2">
              <Label>Rotation Interval (hours)</Label>
              <Input
                type="number"
                value={draft.rotation_interval_hours}
                onChange={(e) => updateField('rotation_interval_hours', parseInt(e.target.value, 10) || 0)}
              />
            </div>
            <div className="space-y-2">
              <Label>Cooldown Hours</Label>
              <Input
                type="number"
                value={draft.cooldown_hours}
                onChange={(e) => updateField('cooldown_hours', parseInt(e.target.value, 10) || 0)}
              />
            </div>
          </CardContent>
        </Card>

        {/* Humanization Settings */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Humanization</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Preset Selection */}
            <div className="space-y-2">
              <Label>Preset</Label>
              <Select
                value={draft.humanization_preset}
                onValueChange={(value) => handlePresetChange(value as Settings['humanization_preset'])}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="low">Low (minimal delays)</SelectItem>
                  <SelectItem value="medium">Medium (moderate delays)</SelectItem>
                  <SelectItem value="high">High (realistic delays)</SelectItem>
                  <SelectItem value="custom">Custom</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Enable/Disable Toggle */}
            <div className="flex items-center justify-between">
              <Label>Enable Humanization</Label>
              <Select
                value={draft.humanization_enabled ? 'true' : 'false'}
                onValueChange={(value) => updateField('humanization_enabled', value === 'true')}
              >
                <SelectTrigger className="w-32">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="true">Enabled</SelectItem>
                  <SelectItem value="false">Disabled</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <Separator />

            {/* Advanced Settings */}
            <div className="space-y-4">
              <h4 className="font-medium text-sm text-muted-foreground">Advanced Settings</h4>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label>Pre-stream Min (sec)</Label>
                  <Input
                    type="number"
                    value={draft.pre_stream_min_sec}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10) || 0
                      updateField('pre_stream_min_sec', val)
                      checkCustomPreset({ ...draft, pre_stream_min_sec: val })
                    }}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Pre-stream Max (sec)</Label>
                  <Input
                    type="number"
                    value={draft.pre_stream_max_sec}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10) || 0
                      updateField('pre_stream_max_sec', val)
                      checkCustomPreset({ ...draft, pre_stream_max_sec: val })
                    }}
                  />
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label>Between Tracks Min (sec)</Label>
                  <Input
                    type="number"
                    value={draft.between_tracks_min_sec}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10) || 0
                      updateField('between_tracks_min_sec', val)
                      checkCustomPreset({ ...draft, between_tracks_min_sec: val })
                    }}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Between Tracks Max (sec)</Label>
                  <Input
                    type="number"
                    value={draft.between_tracks_max_sec}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10) || 0
                      updateField('between_tracks_max_sec', val)
                      checkCustomPreset({ ...draft, between_tracks_max_sec: val })
                    }}
                  />
                </div>
              </div>

              <div className="flex items-center justify-between">
                <Label>Random Actions</Label>
                <Select
                  value={draft.random_actions_enabled ? 'true' : 'false'}
                  onValueChange={(value) => {
                    const checked = value === 'true'
                    updateField('random_actions_enabled', checked)
                    checkCustomPreset({ ...draft, random_actions_enabled: checked })
                  }}
                >
                  <SelectTrigger className="w-32">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="true">Enabled</SelectItem>
                    <SelectItem value="false">Disabled</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label>Min Actions Per Stream</Label>
                  <Input
                    type="number"
                    value={draft.min_actions_per_stream}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10) || 0
                      updateField('min_actions_per_stream', val)
                      checkCustomPreset({ ...draft, min_actions_per_stream: val })
                    }}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Max Actions Per Stream</Label>
                  <Input
                    type="number"
                    value={draft.max_actions_per_stream}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10) || 0
                      updateField('max_actions_per_stream', val)
                      checkCustomPreset({ ...draft, max_actions_per_stream: val })
                    }}
                  />
                </div>
              </div>

              <h4 className="font-medium text-sm text-muted-foreground pt-2">Warmup-specific Delays</h4>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label>Warmup Between Tracks Min (sec)</Label>
                  <Input
                    type="number"
                    value={draft.warmup_between_tracks_min_sec}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10) || 0
                      updateField('warmup_between_tracks_min_sec', val)
                      checkCustomPreset({ ...draft, warmup_between_tracks_min_sec: val })
                    }}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Warmup Between Tracks Max (sec)</Label>
                  <Input
                    type="number"
                    value={draft.warmup_between_tracks_max_sec}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10) || 0
                      updateField('warmup_between_tracks_max_sec', val)
                      checkCustomPreset({ ...draft, warmup_between_tracks_max_sec: val })
                    }}
                  />
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Account Creation Settings */}
        <Card>
          <CardHeader>
            <CardTitle>Account Creation</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Default Account Type</Label>
              <Select
                value={draft.default_account_type}
                onValueChange={(value) => updateField('default_account_type', value as Settings['default_account_type'])}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="free">Free</SelectItem>
                  <SelectItem value="premium">Premium</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Warmup Duration (days)</Label>
              <Input
                type="number"
                value={draft.warmup_duration_days}
                onChange={(e) => updateField('warmup_duration_days', parseInt(e.target.value, 10) || 0)}
              />
            </div>
            <div className="space-y-2">
              <Label>Daily Account Creation Cap</Label>
              <Input
                type="number"
                value={draft.daily_account_creation_cap}
                onChange={(e) => updateField('daily_account_creation_cap', parseInt(e.target.value, 10) || 0)}
              />
            </div>
          </CardContent>
        </Card>

        {/* System Settings */}
        <Card>
          <CardHeader>
            <CardTitle>System</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Daily Reset Hour (0-23)</Label>
              <Input
                type="number"
                min={0}
                max={23}
                value={draft.daily_reset_hour}
                onChange={(e) => updateField('daily_reset_hour', parseInt(e.target.value, 10) || 0)}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      <Separator />

      <div className="flex gap-4 items-center">
        <Button
          onClick={handleSave}
          className="bg-spotify hover:bg-spotify-dark"
          disabled={updateSettings.isPending || !hasChanges}
        >
          {updateSettings.isPending ? 'Saving...' : 'Save Settings'}
        </Button>
        <Button
          variant="outline"
          onClick={handleReset}
          disabled={!hasChanges}
        >
          Discard Changes
        </Button>
        {updateSettings.isError && (
          <div className="text-sm text-red-500">
            Failed to save. Please try again.
          </div>
        )}
      </div>
    </div>
  )
}
