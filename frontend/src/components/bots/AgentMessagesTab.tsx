"use client";



import { useEffect, useState } from "react";



import { SaveBar } from "@/components/bots/SaveBar";

import { Toggle } from "@/components/ui/Toggle";

import { useToast } from "@/hooks/useToast";

import { getApiErrorMessage, useBotStore } from "@/store/useBotStore";

import type { BotAgentProfile } from "@/types/agent";



interface AgentMessagesTabProps {

  botId: string;

  profile: BotAgentProfile;

}



export function AgentMessagesTab({ botId, profile }: AgentMessagesTabProps) {

  const saveAgentSettings = useBotStore((state) => state.saveAgentSettings);

  const profileSaving = useBotStore((state) => state.profileSaving[botId] ?? false);

  const { showToast } = useToast();



  const [messageSplit, setMessageSplit] = useState(profile.message_split);

  const [bufferDelaySec, setBufferDelaySec] = useState(

    Math.round(profile.message_buffer_delay / 1000),

  );



  useEffect(() => {

    setMessageSplit(profile.message_split);

    setBufferDelaySec(Math.round(profile.message_buffer_delay / 1000));

  }, [profile]);



  const handleSave = async (): Promise<void> => {

    try {

      await saveAgentSettings(botId, {

        message_split: messageSplit,

        message_buffer_delay: bufferDelaySec * 1000,

      });

      showToast("Настройки сообщений сохранены.", "success");

    } catch (error) {

      showToast(getApiErrorMessage(error, "Не удалось сохранить настройки."), "error");

    }

  };



  return (

    <div className="space-y-6">

      <section className="glass-card">

        <Toggle

          checked={messageSplit}

          onChange={setMessageSplit}

          label="Разделение сообщений"

          description="Делить длинные ответы на несколько коротких сообщений для естественного ритма чата."

        />

      </section>



      <section className="glass-card">

        <div className="mb-4 flex items-center justify-between gap-3">

          <div>

            <p className="text-sm font-medium text-zinc-100">Буфер сообщений</p>

            <p className="text-xs text-zinc-500">

              Задержка перед отправкой ответа для группировки входящих сообщений и экономии токенов.

            </p>

          </div>

          <span className="rounded-lg bg-zinc-900 px-3 py-1 font-mono text-sm text-indigo-300">

            {bufferDelaySec} сек

          </span>

        </div>

        <input

          type="range"

          min={0}

          max={60}

          step={1}

          value={bufferDelaySec}

          onChange={(event) => setBufferDelaySec(Number(event.target.value))}

          className="w-full accent-indigo-500"

        />

        <div className="mt-3 flex items-center gap-3">

          <input

            type="number"

            min={0}

            max={60}

            value={bufferDelaySec}

            onChange={(event) => setBufferDelaySec(Number(event.target.value))}

            className="w-24 rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2 text-sm text-zinc-100"

          />

          <span className="text-xs text-zinc-500">секунд (0 – 60)</span>

        </div>

      </section>



      <SaveBar onSave={handleSave} saving={profileSaving} />

    </div>

  );

}


